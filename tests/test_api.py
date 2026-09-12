"""Tests for scripts/api.py — FastAPI endpoint POST /v1/responses.

All tests mock run_agent so no real LLM or DB calls are made.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from scripts.api import _MAX_INPUT_LEN, app

client = TestClient(app)


def _fake_run_agent(messages, state=None):
    """Minimal AgentState returned by a mocked run_agent."""
    prior = list(state["messages"]) if state else []
    return {"messages": prior + list(messages) + [AIMessage(content="Respuesta de prueba.")]}


# ── US-005 acceptance criteria ────────────────────────────────────────────────


def test_happy_path_string_input():
    """POST /v1/responses with a string input returns the expected JSON shape."""
    with patch("scripts.api.run_agent", side_effect=_fake_run_agent):
        resp = client.post("/v1/responses", json={"input": "hola"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "response"
    assert data["status"] == "completed"
    assert "conversation_id" in data
    assert data["id"].startswith("resp_")
    assert isinstance(data["created_at"], int)
    output = data["output"]
    assert len(output) == 1
    assert output[0]["type"] == "message"
    assert output[0]["role"] == "assistant"
    assert output[0]["content"][0]["type"] == "output_text"
    assert isinstance(output[0]["content"][0]["text"], str)


def test_missing_input_returns_400():
    """A request without 'input' must return 400 with the error shape."""
    resp = client.post("/v1/responses", json={"model": "gpt-4o"})
    assert resp.status_code == 400
    assert "error" in resp.json()
    assert "message" in resp.json()["error"]


def test_empty_string_input_returns_400():
    resp = client.post("/v1/responses", json={"input": ""})
    assert resp.status_code == 400


def test_empty_array_input_returns_400():
    resp = client.post("/v1/responses", json={"input": []})
    assert resp.status_code == 400


def test_unknown_field_does_not_500():
    """Extra fields like 'stream' must be silently ignored — never a 500."""
    with patch("scripts.api.run_agent", side_effect=_fake_run_agent):
        resp = client.post("/v1/responses", json={"input": "hola", "stream": True})
    assert resp.status_code != 500


def test_array_input_accepted():
    """'input' may be an array of {role, content} message objects."""
    payload = {
        "input": [
            {"role": "user", "content": "¿Dónde estudió Ernesto?"},
        ]
    }
    with patch("scripts.api.run_agent", side_effect=_fake_run_agent):
        resp = client.post("/v1/responses", json=payload)
    assert resp.status_code == 200


def test_conversation_continuity():
    """Two consecutive requests with the same conversation_id share state."""
    calls: list = []

    def _recording_run_agent(messages, state=None):
        calls.append({"messages": messages, "state": state})
        return _fake_run_agent(messages, state=state)

    with patch("scripts.api.run_agent", side_effect=_recording_run_agent):
        r1 = client.post("/v1/responses", json={"input": "turno 1"})
        conv_id = r1.json()["conversation_id"]

        client.post("/v1/responses", json={"input": "turno 2", "conversation_id": conv_id})

    # Second call must have received a non-None state (the saved state from turn 1)
    assert calls[1]["state"] is not None, "Second turn must receive prior AgentState"
    prior_msgs = calls[1]["state"]["messages"]
    assert len(prior_msgs) >= 2  # at least HumanMessage + AIMessage from turn 1


def test_conversation_id_echoed_back():
    """The response must echo the conversation_id sent in the request."""
    with patch("scripts.api.run_agent", side_effect=_fake_run_agent):
        resp = client.post(
            "/v1/responses",
            json={"input": "hola", "conversation_id": "my-custom-id"},
        )
    assert resp.json()["conversation_id"] == "my-custom-id"


# ── US-006 guardrail: input length ────────────────────────────────────────────


def test_input_exceeding_max_length_returns_400():
    """Input string longer than _MAX_INPUT_LEN must be rejected with 400."""
    long_input = "x" * (_MAX_INPUT_LEN + 1)
    resp = client.post("/v1/responses", json={"input": long_input})
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_input_at_max_length_is_accepted():
    """Input exactly at the limit must pass through."""
    boundary_input = "x" * _MAX_INPUT_LEN
    with patch("scripts.api.run_agent", side_effect=_fake_run_agent):
        resp = client.post("/v1/responses", json={"input": boundary_input})
    assert resp.status_code == 200
