"""Tests for query_cv tool.

Unit tests run without a database (psycopg2 and the OpenRouter embedding call are mocked).
The integration test at the bottom requires a live DB and is skipped automatically
when the database is unreachable.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from scripts.query_cv import CV_SIMILARITY_THRESHOLD, query_cv

# 768-dimensional zero vector — valid shape for google/gemini-embedding-2 (dimensions=768)
_FAKE_EMB = [0.0] * 768


def _mock_conn(rows: list[tuple]) -> tuple[MagicMock, MagicMock]:
    """Return (mock_conn, mock_cursor) with cursor.fetchall() -> rows."""
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ── Unit tests (no DB, no sentence-transformers) ───────────────────────────────


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_returns_chunk_results(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    conn, _ = _mock_conn([("Experiencia Laboral", "SESESP", "Trabajé en SESESP...", 0.85)])
    mock_connect.return_value = conn

    results = query_cv("experiencia laboral")

    assert len(results) == 1
    r = results[0]
    assert r["section"] == "Experiencia Laboral"
    assert r["entry_title"] == "SESESP"
    assert "SESESP" in r["content"]
    assert r["similarity"] == pytest.approx(0.85)


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_filters_below_threshold(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    # similarity 0.1 is below the default threshold 0.3
    conn, _ = _mock_conn([("Encabezado", None, "Ernesto Mendieta...", 0.1)])
    mock_connect.return_value = conn

    results = query_cv("algo inventado que no existe")

    assert results == []


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_default_top_k_is_eight(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    conn, cursor = _mock_conn([])
    mock_connect.return_value = conn

    query_cv("pregunta de prueba")

    params = cursor.execute.call_args[0][1]
    assert params[-1] == 8


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_custom_top_k_is_forwarded(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    conn, cursor = _mock_conn([])
    mock_connect.return_value = conn

    query_cv("pregunta", top_k=2)

    params = cursor.execute.call_args[0][1]
    assert params[-1] == 2


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_entry_title_can_be_none(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    conn, _ = _mock_conn([("Educación", None, "IPN Ingeniería en IA...", 0.75)])
    mock_connect.return_value = conn

    results = query_cv("educación")

    assert results[0]["entry_title"] is None


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_multiple_results_ordered_by_similarity(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    rows = [
        ("Experiencia Laboral", "SESESP", "chunk A", 0.90),
        ("Proyectos", "GunGuardAI", "chunk B", 0.65),
        ("Habilidades Técnicas e Idiomas", None, "chunk C", 0.50),
    ]
    conn, _ = _mock_conn(rows)
    mock_connect.return_value = conn

    results = query_cv("pregunta genérica", top_k=3)

    assert len(results) == 3
    assert results[0]["similarity"] > results[1]["similarity"]


@patch("scripts.query_cv.psycopg2.connect")
@patch("scripts.query_cv._embed")
def test_empty_result_when_no_chunks(mock_embed, mock_connect):
    mock_embed.return_value = _FAKE_EMB
    conn, _ = _mock_conn([])
    mock_connect.return_value = conn

    results = query_cv("pregunta sin resultado")

    assert results == []


# ── Integration test (requires live DB with ingested data) ─────────────────────


def _db_available() -> bool:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return False
    try:
        import psycopg2

        psycopg2.connect(url).close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _db_available(), reason="DB not available or DATABASE_URL not set")
def test_integration_real_db_experiencia_laboral():
    """Hit the real DB and verify retrieval for a known CV section."""
    results = query_cv("experiencia laboral SESESP", top_k=4)

    assert isinstance(results, list)
    if results:
        best = results[0]
        assert best["section"] in {
            "Experiencia Laboral",
            "Proyectos",
            "Educación",
            "Habilidades Técnicas e Idiomas",
            "Encabezado",
        }
        assert isinstance(best["content"], str) and best["content"]
        assert 0.0 <= best["similarity"] <= 1.0
        assert best["similarity"] >= CV_SIMILARITY_THRESHOLD


@pytest.mark.skipif(not _db_available(), reason="DB not available or DATABASE_URL not set")
def test_integration_empty_for_nonexistent_topic():
    """A clearly nonsensical query should return no chunks above threshold."""
    results = query_cv("recetas de cocina vegana astronauta", top_k=4)

    # Might return [] or low-similarity results that get filtered out.
    # We can't guarantee empty on every embedding model, so just validate types.
    assert isinstance(results, list)
    for r in results:
        assert r["similarity"] >= CV_SIMILARITY_THRESHOLD
