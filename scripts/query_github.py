"""Tool query_github — GitHub REST API v3 queries for the candidate's public repos."""

from __future__ import annotations

import base64
import os
from typing import TypedDict

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_USERNAME = os.environ["GITHUB_USERNAME"]
GITHUB_API_BASE = "https://api.github.com"

# Optional: comma-separated allowlist (e.g. ALLOWED_REPOS=repo-a,repo-b).
# When set, list_repos is filtered and repo_name is validated against this set.
_ALLOWED_RAW = os.environ.get("ALLOWED_REPOS", "")
ALLOWED_REPOS: set[str] = (
    {r.strip() for r in _ALLOWED_RAW.split(",") if r.strip()} if _ALLOWED_RAW else set()
)

TOOL_SCHEMA = {
    "name": "query_github",
    "description": (
        "Consulta los repositorios públicos de GitHub del candidato: lista de repos, "
        "detalle de un repo, lenguajes usados, contenido del README, o actividad "
        "reciente (commits)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "aspect": {
                "type": "string",
                "enum": ["list_repos", "repo_overview", "languages", "readme", "activity"],
                "description": "Qué aspecto consultar.",
            },
            "repo_name": {
                "type": "string",
                "description": (
                    "Nombre del repo (sin owner). Requerido para todo aspecto "
                    "excepto 'list_repos'."
                ),
            },
        },
        "required": ["aspect"],
    },
}


class GithubResult(TypedDict):
    ok: bool
    data: dict | list | None
    error: str | None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def _is_rate_limited(response: requests.Response) -> bool:
    remaining = response.headers.get("X-RateLimit-Remaining", "1")
    try:
        return int(remaining) == 0
    except ValueError:
        return False


def query_github(aspect: str, repo_name: str | None = None) -> GithubResult:
    """Query GitHub REST API v3 for the candidate's public repos.

    Never raises uncaught exceptions — all errors are returned as GithubResult.
    """
    base = GITHUB_API_BASE
    user = GITHUB_USERNAME

    if aspect != "list_repos" and not repo_name:
        return GithubResult(ok=False, data=None, error="repo_name_required")

    if repo_name and ALLOWED_REPOS and repo_name not in ALLOWED_REPOS:
        return GithubResult(ok=False, data=None, error="repo_not_allowed")

    url_map: dict[str, str] = {
        "list_repos": f"{base}/users/{user}/repos",
        "repo_overview": f"{base}/repos/{user}/{repo_name}",
        "languages": f"{base}/repos/{user}/{repo_name}/languages",
        "readme": f"{base}/repos/{user}/{repo_name}/readme",
        "activity": f"{base}/repos/{user}/{repo_name}/commits?per_page=5",
    }

    if aspect not in url_map:
        return GithubResult(ok=False, data=None, error="invalid_aspect")

    try:
        response = _session().get(url_map[aspect], timeout=10)
    except requests.RequestException as exc:
        return GithubResult(ok=False, data=None, error=f"network_error: {exc}")

    if response.status_code == 404:
        return GithubResult(ok=False, data=None, error="repo_not_found")

    if response.status_code == 403 or _is_rate_limited(response):
        return GithubResult(ok=False, data=None, error="rate_limited")

    if not response.ok:
        return GithubResult(ok=False, data=None, error=f"github_error_{response.status_code}")

    payload = response.json()

    if aspect == "readme":
        raw_b64 = payload.get("content", "").replace("\n", "")
        text = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
        return GithubResult(ok=True, data={"name": payload.get("name", ""), "content": text}, error=None)

    if aspect == "list_repos":
        repos = payload
        if ALLOWED_REPOS:
            repos = [r for r in repos if r["name"] in ALLOWED_REPOS]
        normalized = [
            {
                "name": r["name"],
                "description": r.get("description"),
                "stars": r.get("stargazers_count", 0),
                "language": r.get("language"),
                "updated_at": r.get("updated_at"),
            }
            for r in repos
        ]
        return GithubResult(ok=True, data=normalized, error=None)

    if aspect == "repo_overview":
        normalized = {
            "name": payload.get("name"),
            "description": payload.get("description"),
            "stars": payload.get("stargazers_count", 0),
            "forks": payload.get("forks_count", 0),
            "language": payload.get("language"),
            "topics": payload.get("topics", []),
            "updated_at": payload.get("updated_at"),
        }
        return GithubResult(ok=True, data=normalized, error=None)

    if aspect == "activity":
        normalized = [
            {
                "sha": c["sha"][:7],
                "message": c["commit"]["message"].split("\n")[0],
                "author": c["commit"]["author"].get("name"),
                "date": c["commit"]["author"].get("date"),
            }
            for c in payload
        ]
        return GithubResult(ok=True, data=normalized, error=None)

    # languages — already a simple {lang: bytes} dict
    return GithubResult(ok=True, data=payload, error=None)
