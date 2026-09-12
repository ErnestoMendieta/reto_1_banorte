"""Tests for scripts/query_github.py — unit tests with mocked HTTP responses.

Unit tests run without real network access (_session is mocked).
The integration test at the bottom requires a reachable GitHub API and is
skipped automatically when the token or network is unavailable.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest


def _resp(status: int, body=None, headers: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = body if body is not None else {}
    r.headers = {"X-RateLimit-Remaining": "4999", **(headers or {})}
    return r


def _mock_session(response: MagicMock) -> MagicMock:
    session = MagicMock()
    session.get.return_value = response
    return session


# ── list_repos ────────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_list_repos_returns_normalized_list(mock_session):
    raw = [
        {
            "name": "my-repo",
            "description": "A project",
            "stargazers_count": 3,
            "language": "Python",
            "updated_at": "2025-01-01T00:00:00Z",
        }
    ]
    mock_session.return_value = _mock_session(_resp(200, raw))

    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert result["ok"] is True
    assert isinstance(result["data"], list)
    assert result["data"][0]["name"] == "my-repo"
    assert result["error"] is None


@patch("scripts.query_github._session")
def test_list_repos_normalizes_expected_fields(mock_session):
    raw = [
        {"name": "r", "description": None, "stargazers_count": 0, "language": None, "updated_at": None}
    ]
    mock_session.return_value = _mock_session(_resp(200, raw))

    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert set(result["data"][0].keys()) == {
        "owner",
        "name",
        "description",
        "stars",
        "language",
        "updated_at",
    }


@patch("scripts.query_github._session")
@patch("scripts.query_github.GITHUB_USERNAMES", ["userA", "userB"])
def test_list_repos_merges_multiple_accounts_and_tags_owner(mock_session):
    resp_a = _resp(
        200,
        [{"name": "repo-a", "description": None, "stargazers_count": 1, "language": "Python", "updated_at": None}],
    )
    resp_b = _resp(
        200,
        [{"name": "repo-b", "description": None, "stargazers_count": 2, "language": "Go", "updated_at": None}],
    )
    session = MagicMock()
    session.get.side_effect = [resp_a, resp_b]
    mock_session.return_value = session

    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert result["ok"] is True
    assert {r["owner"] for r in result["data"]} == {"userA", "userB"}
    assert {r["name"] for r in result["data"]} == {"repo-a", "repo-b"}


# ── readme ────────────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_readme_returns_decoded_text(mock_session):
    text = "# Hello World\nThis is the README."
    encoded = base64.b64encode(text.encode()).decode() + "\n"  # GitHub adds trailing newline
    mock_session.return_value = _mock_session(_resp(200, {"content": encoded, "name": "README.md"}))

    from scripts.query_github import query_github

    result = query_github("readme", repo_name="my-repo")

    assert result["ok"] is True
    assert result["data"]["content"] == text


@patch("scripts.query_github._session")
def test_readme_content_is_plain_string_not_base64(mock_session):
    text = "# Project\n\nThis repo does something cool."
    encoded = base64.b64encode(text.encode()).decode()
    mock_session.return_value = _mock_session(_resp(200, {"content": encoded, "name": "README.md"}))

    from scripts.query_github import query_github

    result = query_github("readme", repo_name="cool-repo")

    assert result["data"]["content"] == text
    assert isinstance(result["data"]["content"], str)


# ── rate limit ────────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_403_returns_rate_limited(mock_session):
    mock_session.return_value = _mock_session(_resp(403))

    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert result["ok"] is False
    assert result["error"] == "rate_limited"


@patch("scripts.query_github._session")
def test_rate_limit_remaining_zero_returns_rate_limited(mock_session):
    """X-RateLimit-Remaining: 0 triggers rate_limited even on a 200 response."""
    raw = [{"name": "r", "description": None, "stargazers_count": 0, "language": None, "updated_at": None}]
    mock_session.return_value = _mock_session(_resp(200, raw, headers={"X-RateLimit-Remaining": "0"}))

    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert result["ok"] is False
    assert result["error"] == "rate_limited"


# ── repo not found ────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_repo_not_found_returns_error(mock_session):
    mock_session.return_value = _mock_session(_resp(404, {"message": "Not Found"}))

    from scripts.query_github import query_github

    result = query_github("repo_overview", repo_name="nonexistent-repo")

    assert result["ok"] is False
    assert result["error"] == "repo_not_found"


@patch("scripts.query_github._session")
def test_readme_repo_not_found(mock_session):
    mock_session.return_value = _mock_session(_resp(404, {"message": "Not Found"}))

    from scripts.query_github import query_github

    result = query_github("readme", repo_name="nonexistent-repo")

    assert result["ok"] is False
    assert result["error"] == "repo_not_found"


# ── validation ────────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_missing_repo_name_returns_error(mock_session):
    from scripts.query_github import query_github

    result = query_github("readme")

    assert result["ok"] is False
    assert result["error"] == "repo_name_required"
    mock_session.assert_not_called()


# ── owner param ───────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_repo_overview_uses_specified_owner(mock_session):
    session = MagicMock()
    session.get.return_value = _resp(
        200,
        {"name": "r", "stargazers_count": 0, "forks_count": 0, "language": None, "topics": [], "updated_at": None},
    )
    mock_session.return_value = session

    from scripts.query_github import query_github

    query_github("repo_overview", repo_name="r", owner="someone-else")

    called_url = session.get.call_args[0][0]
    assert "someone-else/r" in called_url


@patch("scripts.query_github._session")
def test_repo_overview_defaults_to_primary_owner_when_omitted(mock_session):
    session = MagicMock()
    session.get.return_value = _resp(
        200,
        {"name": "r", "stargazers_count": 0, "forks_count": 0, "language": None, "topics": [], "updated_at": None},
    )
    mock_session.return_value = session

    from scripts.query_github import GITHUB_USERNAMES, query_github

    query_github("repo_overview", repo_name="r")

    called_url = session.get.call_args[0][0]
    assert f"{GITHUB_USERNAMES[0]}/r" in called_url


# ── network error ─────────────────────────────────────────────────────────────


@patch("scripts.query_github._session")
def test_network_error_does_not_raise(mock_session):
    import requests as req_lib

    mock_session.return_value.get.side_effect = req_lib.RequestException("connection refused")

    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert result["ok"] is False
    assert "network_error" in result["error"]


# ── integration (skipped without real network + valid token) ──────────────────


def _github_available() -> bool:
    import os

    token = os.environ.get("GITHUB_TOKEN", "")
    usernames = os.environ.get("GITHUB_USERNAMES", "")
    if not token or not usernames:
        return False
    try:
        import requests as req

        username = usernames.split(",")[0].strip()
        r = req.get(
            f"https://api.github.com/users/{username}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _github_available(), reason="GitHub API not reachable or credentials not set")
def test_integration_list_repos_real():
    from scripts.query_github import query_github

    result = query_github("list_repos")

    assert result["ok"] is True
    assert isinstance(result["data"], list)
    if result["data"]:
        assert "name" in result["data"][0]
        assert "stars" in result["data"][0]
