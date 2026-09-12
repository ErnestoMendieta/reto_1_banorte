"""Tool query_cv — semantic retrieval over the CV stored in Postgres+pgvector."""

from __future__ import annotations

import logging
import os
import time

os.environ.setdefault("USE_TF", "0")  # avoid transformers loading TF/Keras 3 on this machine

from typing import TypedDict

import psycopg2
from dotenv import load_dotenv

load_dotenv()

from scripts.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
CV_SIMILARITY_THRESHOLD = float(os.environ.get("CV_SIMILARITY_THRESHOLD", "0.3"))

_model_cache: dict = {}

TOOL_SCHEMA = {
    "name": "query_cv",
    "description": (
        "Busca información en el CV del candidato (experiencia, educación, skills, "
        "proyectos) relevante a una pregunta. Devuelve únicamente texto extraído del "
        "CV, nunca información inventada."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Pregunta o tema a buscar en el CV, en lenguaje natural.",
            },
            "top_k": {
                "type": "integer",
                "description": "Número de fragmentos a devolver.",
                "default": 4,
            },
        },
        "required": ["question"],
    },
}


class ChunkResult(TypedDict):
    section: str
    entry_title: str | None
    content: str
    similarity: float  # cosine similarity 0-1, higher = more similar


def _load_model():
    if EMBEDDING_MODEL not in _model_cache:
        from sentence_transformers import SentenceTransformer

        start = time.perf_counter()
        _model_cache[EMBEDDING_MODEL] = SentenceTransformer(EMBEDDING_MODEL)
        logger.info(
            "model_load",
            extra={
                "embedding_model": EMBEDDING_MODEL,
                "cache_hit": False,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
    else:
        logger.debug("model_load", extra={"embedding_model": EMBEDDING_MODEL, "cache_hit": True})
    return _model_cache[EMBEDDING_MODEL]


def _vec_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def query_cv(question: str, top_k: int = 4) -> list[ChunkResult]:
    """Return top_k CV chunks semantically closest to question.

    Chunks below CV_SIMILARITY_THRESHOLD (env var, default 0.3) are dropped.
    Returns [] when nothing qualifies.
    """
    model = _load_model()
    query_vec = _vec_to_pg(model.encode(question))

    start = time.perf_counter()
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception:
        logger.exception("query_cv_error", extra={"question": question})
        raise
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.section, d.entry_title, d.content,
                       1 - (e.embedding <=> %s::vector) AS similarity
                FROM cv_embeddings e
                JOIN cv_documents d ON d.id = e.document_id
                WHERE e.model_name = %s
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, EMBEDDING_MODEL, query_vec, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    results = [
        ChunkResult(
            section=row[0],
            entry_title=row[1],
            content=row[2],
            similarity=float(row[3]),
        )
        for row in rows
        if float(row[3]) >= CV_SIMILARITY_THRESHOLD
    ]
    logger.info(
        "query_cv_result",
        extra={
            "question": question,
            "top_k": top_k,
            "num_results": len(results),
            "top_similarity": float(rows[0][3]) if rows else None,
            "below_threshold_count": len(rows) - len(results),
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        },
    )
    return results
