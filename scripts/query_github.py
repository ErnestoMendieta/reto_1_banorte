"""Tool query_github — GitHub REST API v3 queries for the candidate's public repos."""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import TypedDict

import requests
from dotenv import load_dotenv

load_dotenv()

from scripts.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_USERNAMES: list[str] = [
    u.strip() for u in os.environ["GITHUB_USERNAMES"].split(",") if u.strip()
]
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
        "Consulta los repos públicos de GitHub del candidato (puede tener varias cuentas): "
        "lista de repos, detalle, lenguajes, README o commits recientes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "aspect": {
                "type": "string",
                "enum": ["list_repos", "repo_overview", "languages", "readme", "activity"],
                "description": (
                    "Qué consultar: list_repos, repo_overview (descripción/stars/forks), "
                    "languages, readme, o activity (últimos commits)."
                ),
            },
            "repo_name": {
                "type": "string",
                "description": "Nombre del repo (sin owner). Requerido salvo en 'list_repos'.",
            },
            "owner": {
                "type": "string",
                "description": (
                    "Cuenta dueña del repo (campo 'owner' de list_repos). "
                    "Si se omite, usa la cuenta principal del candidato."
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


def query_github(aspect: str, repo_name: str | None = None, owner: str | None = None) -> GithubResult:
    """Query GitHub REST API v3 for the candidate's public repos.

    Never raises uncaught exceptions — all errors are returned as GithubResult.
    Thin logging wrapper around _query_github_impl; see that function for the actual logic.
    """
    logger.debug(
        "query_github_start", extra={"aspect": aspect, "repo_name": repo_name, "owner": owner}
    )
    start = time.perf_counter()
    result = _query_github_impl(aspect, repo_name, owner)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    error = result["error"] or ""
    common = {"aspect": aspect, "repo_name": repo_name, "owner": owner, "latency_ms": latency_ms}
    if error == "rate_limited":
        logger.warning("query_github_rate_limited", extra=common)
    elif error.startswith("network_error"):
        logger.warning("query_github_network_error", extra={**common, "error": error})
    else:
        result_size = len(result["data"]) if isinstance(result["data"], list) else int(bool(result["data"]))
        logger.info(
            "query_github_result",
            extra={**common, "ok": result["ok"], "error": result["error"], "result_size": result_size},
        )
    return result


def _list_repos_all_accounts() -> GithubResult:
    """Fetch and merge public repos across every account in GITHUB_USERNAMES.

    Fails fast on the first account that errors out — consistent with the
    single-request error handling used for every other aspect.
    """
    all_repos: list[dict] = []
    for user in GITHUB_USERNAMES:
        try:
            response = _session().get(f"{GITHUB_API_BASE}/users/{user}/repos", timeout=10)
        except requests.RequestException as exc:
            return GithubResult(ok=False, data=None, error=f"network_error: {exc}")

        if response.status_code == 403 or _is_rate_limited(response):
            return GithubResult(ok=False, data=None, error="rate_limited")

        if not response.ok:
            return GithubResult(ok=False, data=None, error=f"github_error_{response.status_code}")

        for r in response.json():
            if ALLOWED_REPOS and r["name"] not in ALLOWED_REPOS:
                continue
            all_repos.append(
                {
                    "owner": user,
                    "name": r["name"],
                    "description": r.get("description"),
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language"),
                    "updated_at": r.get("updated_at"),
                }
            )
    return GithubResult(ok=True, data=all_repos, error=None)


def _query_github_impl(
    aspect: str, repo_name: str | None = None, owner: str | None = None
) -> GithubResult:
    """Query GitHub REST API v3 for the candidate's public repos.

    Never raises uncaught exceptions — all errors are returned as GithubResult.
    """
    base = GITHUB_API_BASE

    if aspect != "list_repos" and not repo_name:
        return GithubResult(ok=False, data=None, error="repo_name_required")

    if repo_name and ALLOWED_REPOS and repo_name not in ALLOWED_REPOS:
        return GithubResult(ok=False, data=None, error="repo_not_allowed")

    if aspect == "list_repos":
        return _list_repos_all_accounts()

    user = owner or GITHUB_USERNAMES[0]
    url_map: dict[str, str] = {
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
