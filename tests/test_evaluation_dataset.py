"""Tests for evaluation/dataset.json — pure schema/static validation.

Does NOT run the agent, hit the DB, or call the network. Only guards against
the dataset file becoming invalid JSON or silently violating its own schema
(see evaluation/README.md for the schema definition).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

DATASET_PATH = Path(__file__).parent.parent / "evaluation" / "dataset.json"

_CATEGORIES = {
    "cv_direct",
    "github",
    "multi_tool",
    "continuity",
    "out_of_scope",
    "small_talk",
    "adversarial",
}
_CHECK_TYPES = {
    "keyword_match",
    "refusal",
    "no_tool_call",
    "graceful_degradation",
    "adversarial_guardrail",
}
_MATCH_MODES = {"all", "any", "none"}
_TOOL_NAMES = {"query_cv_tool", "query_github_tool"}
_REQUIRED_FIELDS = {
    "id",
    "category",
    "description",
    "turns",
    "expected_tool_calls",
    "expected_tool_calls_match",
    "check_type",
    "expected_behavior",
    "repeat",
    "runnable_live",
}


def _load_dataset() -> dict:
    with open(DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_dataset_file_is_valid_json():
    data = _load_dataset()
    assert isinstance(data, dict)
    assert "cases" in data and isinstance(data["cases"], list)


def test_case_count_is_reasonable():
    data = _load_dataset()
    assert 20 <= len(data["cases"]) <= 25


def test_case_ids_are_unique():
    data = _load_dataset()
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", _load_dataset()["cases"], ids=lambda c: c["id"])
def test_case_matches_schema(case: dict):
    assert _REQUIRED_FIELDS.issubset(case.keys()), f"{case.get('id')} missing fields"

    assert case["category"] in _CATEGORIES
    assert case["check_type"] in _CHECK_TYPES
    assert case["expected_tool_calls_match"] in _MATCH_MODES
    assert isinstance(case["repeat"], int) and case["repeat"] >= 1
    assert isinstance(case["runnable_live"], bool)
    assert isinstance(case["expected_behavior"], str) and case["expected_behavior"]

    assert isinstance(case["turns"], list) and len(case["turns"]) >= 1
    for turn in case["turns"]:
        assert turn["role"] == "user"
        assert isinstance(turn["content"], str) and turn["content"]

    for tc in case["expected_tool_calls"]:
        assert tc["name"] in _TOOL_NAMES

    if case["expected_tool_calls_match"] == "none":
        assert case["expected_tool_calls"] == []

    if case["category"] == "adversarial":
        assert case["repeat"] == 3, f"{case['id']}: adversarial cases must repeat 3x (US-006)"

    if case["category"] == "continuity":
        assert len(case["turns"]) >= 2, f"{case['id']}: continuity cases need >=2 turns"
