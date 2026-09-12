"""Unit tests for CV parsing logic — no database required."""

from pathlib import Path

from scripts.ingest_cv import clean_latex, parse_cv

CV_PATH = str(Path(__file__).parent.parent / "data" / "cv.tex")


def test_parse_cv_returns_chunks():
    chunks = parse_cv(CV_PATH)
    assert len(chunks) >= 10


def test_parse_cv_required_sections_present():
    chunks = parse_cv(CV_PATH)
    sections = {c["section"] for c in chunks}
    assert "Educación" in sections
    assert "Experiencia Laboral" in sections
    assert "Proyectos" in sections
    assert "Habilidades Técnicas e Idiomas" in sections


def test_experiencia_laboral_splits_into_three_entries():
    chunks = parse_cv(CV_PATH)
    exp = [c for c in chunks if c["section"] == "Experiencia Laboral"]
    assert len(exp) == 3


def test_proyectos_splits_into_five_entries():
    chunks = parse_cv(CV_PATH)
    proj = [c for c in chunks if c["section"] == "Proyectos"]
    assert len(proj) == 5


def test_entry_titles_are_extracted():
    chunks = parse_cv(CV_PATH)
    exp = [c for c in chunks if c["section"] == "Experiencia Laboral"]
    titles = [c["entry_title"] for c in exp]
    assert all(t is not None for t in titles)
    # SESESP is the longest company name and includes the acronym
    assert any("SESESP" in (t or "") for t in titles)


def test_project_entry_titles_extracted():
    chunks = parse_cv(CV_PATH)
    proj = [c for c in chunks if c["section"] == "Proyectos"]
    titles = [c["entry_title"] for c in proj]
    assert all(t is not None for t in titles)
    assert any("GunGuardAI" in (t or "") for t in titles)


def test_no_raw_latex_in_content():
    chunks = parse_cv(CV_PATH)
    for chunk in chunks:
        assert "\\textbf" not in chunk["content"]
        assert "\\begin" not in chunk["content"]
        assert "\\item" not in chunk["content"]
        assert "\\hfill" not in chunk["content"]


def test_metadata_has_required_fields():
    chunks = parse_cv(CV_PATH)
    for chunk in chunks:
        assert "raw_length" in chunk["metadata"]
        assert "source" in chunk["metadata"]
        assert chunk["metadata"]["source"] == "cv.tex"


def test_parse_cv_is_deterministic():
    chunks1 = parse_cv(CV_PATH)
    chunks2 = parse_cv(CV_PATH)
    assert chunks1 == chunks2


def test_clean_latex_strips_textbf():
    result = clean_latex(r"\textbf{Hola Mundo}")
    assert "Hola Mundo" in result
    assert "\\textbf" not in result


def test_clean_latex_strips_hfill():
    result = clean_latex(r"Texto \hfill Derecha")
    assert "Texto" in result
    assert "\\hfill" not in result


def test_clean_latex_handles_href():
    result = clean_latex(r"\href{https://example.com}{Ver enlace}")
    assert "Ver enlace" in result
    assert "https://example.com" not in result


def test_clean_latex_handles_item():
    result = clean_latex(r"\begin{itemize}\item Primera\item Segunda\end{itemize}")
    assert "Primera" in result
    assert "Segunda" in result
    assert "\\item" not in result
