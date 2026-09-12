"""Ingest the CV LaTeX source into Postgres+pgvector.

Usage:
    python scripts/ingest_cv.py            # full parse + embed
    python scripts/ingest_cv.py --reembed  # re-embed only (skip re-parse)
"""

from __future__ import annotations

import argparse
import json
import os

os.environ.setdefault("USE_TF", "0")  # avoid transformers loading TF/Keras 3 on this machine

import re
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]
CV_TEX_PATH = os.environ.get("CV_TEX_PATH", "./data/cv.tex")
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "384"))


# ── LaTeX parsing ──────────────────────────────────────────────────────────────

def clean_latex(text: str) -> str:
    """Strip LaTeX markup and return readable plain text."""
    # Remove % comments
    text = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    # Preserve bullet glyphs before generic command removal
    text = text.replace("\\textbullet", "•")
    # LaTeX line breaks \\[dim] or \\ → newline
    text = re.sub(r"\\\\(\[[^\]]*\])?", "\n", text)
    # \href{url}{label} → label
    text = re.sub(r"\\href\{[^}]+\}\{([^}]+)\}", r"\1", text)
    # Remove \begin{env}[opts] and \end{env}
    text = re.sub(r"\\begin\{[^}]+\}(\[[^\]]*\])?", "", text)
    text = re.sub(r"\\end\{[^}]+\}", "", text)
    # \item → bullet
    text = re.sub(r"\\item\s*", "• ", text)
    # Text formatting commands with content: \textbf{x}, \textit{x}, \MakeUppercase{x}
    text = re.sub(r"\\(?:textbf|textit|textrm|MakeUppercase)\{([^}]*)\}", r"\1", text)
    # Font-size group: {\LARGE content} → content
    text = re.sub(r"\{\\[A-Z][A-Za-z]*\s+([^}]*)\}", r"\1", text)
    # Remove commands with brace arguments: \vspace{...}, \hspace{...}, etc.
    text = re.sub(r"\\[a-zA-Z]+\{[^}]*\}", "", text)
    # Remove standalone commands: \hfill, \newpage, \noindent, etc.
    text = re.sub(r"\\[a-zA-Z]+\b", "", text)
    # Backslash-space (LaTeX hard space) → regular space
    text = text.replace("\\ ", " ")
    # Remove orphan braces
    text = text.replace("{", "").replace("}", "")
    # Remove leftover [...] option fragments
    text = re.sub(r"\[[^\]]*\]", "", text)
    # Normalize whitespace
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def _split_entries(section_content: str, section_name: str) -> list[tuple[str | None, str]]:
    """Split a section into individual entries (jobs / projects).

    Experiencia Laboral entries are separated by \\vspace{8pt};
    Proyectos entries by \\vspace{6pt}.
    """
    sep = "\\vspace{8pt}" if section_name == "Experiencia Laboral" else "\\vspace{6pt}"
    parts = re.split(re.escape(sep), section_content)
    entries: list[tuple[str | None, str]] = []
    for raw in parts:
        raw = raw.strip()
        if not raw:
            continue
        m = re.search(r"\\textbf\{([^}]+)\}", raw)
        entry_title = m.group(1).strip() if m else None
        entries.append((entry_title, raw))
    return entries


def parse_cv(tex_path: str) -> list[dict]:
    """Parse a LaTeX CV into a list of chunks.

    Returns list of dicts: {section, entry_title, content, metadata}.
    Sections "Experiencia Laboral" and "Proyectos" are split per entry.
    """
    source = Path(tex_path).read_text(encoding="utf-8")

    # Drop preamble (everything before \begin{document})
    doc_start = source.find(r"\begin{document}")
    if doc_start != -1:
        source = source[doc_start + len(r"\begin{document}"):]
    source = source.replace(r"\end{document}", "")

    chunks: list[dict] = []

    # The template uses \seccion{Name} (custom macro, not \section)
    section_re = re.compile(r"\\seccion\{([^}]+)\}")
    parts = section_re.split(source)
    # parts = [pre-header, sec1, content1, sec2, content2, ...]

    header_raw = parts[0]
    header_text = clean_latex(header_raw)
    if header_text:
        chunks.append({
            "section": "Encabezado",
            "entry_title": None,
            "content": header_text,
            "metadata": {"raw_length": len(header_raw), "source": "cv.tex"},
        })

    for i in range(1, len(parts), 2):
        sec_name = parts[i].strip()
        sec_content = parts[i + 1] if i + 1 < len(parts) else ""

        if sec_name in ("Experiencia Laboral", "Proyectos"):
            for entry_title, raw in _split_entries(sec_content, sec_name):
                content = clean_latex(raw)
                if content:
                    chunks.append({
                        "section": sec_name,
                        "entry_title": entry_title,
                        "content": content,
                        "metadata": {"raw_length": len(raw), "source": "cv.tex"},
                    })
        else:
            content = clean_latex(sec_content)
            if content:
                chunks.append({
                    "section": sec_name,
                    "entry_title": None,
                    "content": content,
                    "metadata": {"raw_length": len(sec_content), "source": "cv.tex"},
                })

    return chunks


# ── Database helpers ───────────────────────────────────────────────────────────

def setup_schema(conn) -> None:
    """Create extension, tables, and HNSW index if they don't exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cv_documents (
                id          SERIAL PRIMARY KEY,
                section     TEXT NOT NULL,
                entry_title TEXT,
                content     TEXT NOT NULL,
                metadata    JSONB NOT NULL DEFAULT '{}',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS cv_embeddings (
                id          SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL REFERENCES cv_documents(id) ON DELETE CASCADE,
                model_name  TEXT NOT NULL,
                embedding   VECTOR({EMBEDDING_DIM}) NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (document_id, model_name)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS cv_embeddings_embedding_idx
                ON cv_embeddings USING hnsw (embedding vector_cosine_ops)
        """)
    conn.commit()


def _embedding_to_pg(vec: list) -> str:
    """Serialize a float list to a Postgres vector literal '[x,y,...]'."""
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def full_ingest(conn) -> None:
    """Parse CV, truncate tables, insert all chunks and embeddings."""
    chunks = parse_cv(CV_TEX_PATH)
    print(f"Parsed {len(chunks)} chunks from {CV_TEX_PATH}")

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Loaded embedding model: {EMBEDDING_MODEL}")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE cv_documents CASCADE")
        for i, chunk in enumerate(chunks, 1):
            cur.execute(
                "INSERT INTO cv_documents (section, entry_title, content, metadata)"
                " VALUES (%s, %s, %s, %s) RETURNING id",
                (
                    chunk["section"],
                    chunk["entry_title"],
                    chunk["content"],
                    json.dumps(chunk["metadata"]),
                ),
            )
            doc_id = cur.fetchone()[0]
            emb = model.encode(chunk["content"]).tolist()
            cur.execute(
                "INSERT INTO cv_embeddings (document_id, model_name, embedding)"
                " VALUES (%s, %s, %s::vector)",
                (doc_id, EMBEDDING_MODEL, _embedding_to_pg(emb)),
            )
            label = chunk["entry_title"] or "(sección)"
            print(f"  [{i}/{len(chunks)}] {chunk['section']} — {label}")
    conn.commit()
    print("Ingesta completa.")


def reembed_only(conn) -> None:
    """Regenerate embeddings for EMBEDDING_MODEL without re-parsing the CV.

    Uses upsert so existing embeddings for other model_name values are untouched.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id, content FROM cv_documents ORDER BY id")
        docs = cur.fetchall()

    if not docs:
        print("cv_documents está vacía — corre sin --reembed primero.")
        sys.exit(1)

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    print(f"Re-embebiendo {len(docs)} chunks con {EMBEDDING_MODEL}")

    with conn.cursor() as cur:
        for i, (doc_id, content) in enumerate(docs, 1):
            emb = model.encode(content).tolist()
            cur.execute(
                "INSERT INTO cv_embeddings (document_id, model_name, embedding)"
                " VALUES (%s, %s, %s::vector)"
                " ON CONFLICT (document_id, model_name)"
                " DO UPDATE SET embedding = EXCLUDED.embedding, created_at = now()",
                (doc_id, EMBEDDING_MODEL, _embedding_to_pg(emb)),
            )
            print(f"  [{i}/{len(docs)}] doc_id={doc_id}")
    conn.commit()
    print("Re-embedding completo.")


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CV into Postgres+pgvector")
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="Only regenerate embeddings for EMBEDDING_MODEL; skip re-parsing",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    try:
        setup_schema(conn)
        if args.reembed:
            reembed_only(conn)
        else:
            full_ingest(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
