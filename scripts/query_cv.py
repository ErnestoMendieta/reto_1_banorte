"""Tool query_cv — semantic retrieval over the CV stored in Postgres+pgvector."""

from __future__ import annotations

import logging
import os
import time
from typing import TypedDict

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

from scripts.logging_config import setup_logging
from scripts.retry import call_with_rate_limit_retry

setup_logging()
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "google/gemini-embedding-2")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CV_SIMILARITY_THRESHOLD = float(os.environ.get("CV_SIMILARITY_THRESHOLD", "0.15"))

TOOL_SCHEMA = {
    "name": "query_cv",
    "description": (
        "Busca en el CV del candidato (experiencia, educación, skills, proyectos) "
        "fragmentos relevantes a una pregunta. Solo texto extraído del CV, nunca inventado."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "Pregunta o tema a buscar en el CV.",
            },
            "top_k": {
                "type": "integer",
                "description": "Número de fragmentos a devolver.",
                "default": 8,
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


def _embed(text: str) -> list[float]:
    """Get an embedding vector from OpenRouter (qwen3-embedding by default)."""

    def _call():
        resp = requests.post(
            f"{OPENROUTER_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={"model": EMBEDDING_MODEL, "input": text, "dimensions": EMBEDDING_DIM},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]

    return call_with_rate_limit_retry(_call)


def _vec_to_pg(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def query_cv(question: str, top_k: int = 8) -> list[ChunkResult]:
    """Return top_k CV chunks semantically closest to question.

    Chunks below CV_SIMILARITY_THRESHOLD (env var, default 0.3) are dropped.
    Returns [] when nothing qualifies.
    """
    query_vec = _vec_to_pg(_embed(question))

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
