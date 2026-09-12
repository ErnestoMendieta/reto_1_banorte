"""Tests for scripts/orchestrator.py — unit tests with mocked LLM and tool functions.

All tests mock _build_llm() so no real OpenRouter calls are made.
Tool functions (_query_cv, _query_github) are mocked where tool execution is needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from scripts.orchestrator import run_agent


def _tool_call(name: str, args: dict, call_id: str = "call_001") -> dict:
    return {"id": call_id, "name": name, "args": args, "type": "tool_call"}


# ── Test 1: greeting — no tool calls ──────────────────────────────────────────


def test_greeting_produces_no_tool_calls():
    """A simple greeting must not invoke any tool and return a direct AIMessage."""
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(
        content="¡Hola! Soy el asistente de Ernesto. ¿En qué puedo ayudarte?"
    )

    with patch("scripts.orchestrator._build_llm", return_value=mock_llm):
        result = run_agent([HumanMessage(content="hola, ¿cómo estás?")])

    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert not getattr(last, "tool_calls", [])
    mock_llm.invoke.assert_called_once()  # single LLM call, no tool loop


# ── Test 2: CV question — query_cv invoked ────────────────────────────────────


def test_cv_question_invokes_query_cv():
    """A question about experience/skills must trigger query_cv_tool."""
    tc = _tool_call("query_cv_tool", {"question": "¿Dónde trabajó Ernesto?"})
    ai_with_tool = AIMessage(content="", tool_calls=[tc])
    ai_final = AIMessage(content="Ernesto trabajó en SESESP, CIDETEC y CETis 132.")

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [ai_with_tool, ai_final]

    fake_cv = [
        {
            "section": "Experiencia Laboral",
            "entry_title": "SESESP",
            "content": "Desarrollador en SESESP.",
            "similarity": 0.9,
        }
    ]

    with (
        patch("scripts.orchestrator._build_llm", return_value=mock_llm),
        patch("scripts.orchestrator._query_cv", return_value=fake_cv),
    ):
        result = run_agent([HumanMessage(content="¿Dónde trabajó Ernesto?")])

    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert mock_llm.invoke.call_count == 2  # once before tools, once after


# ── Test 3: GitHub question — query_github invoked ────────────────────────────


def test_github_question_invokes_query_github():
    """A question about repos must trigger query_github_tool."""
    tc = _tool_call("query_github_tool", {"aspect": "list_repos"})
    ai_with_tool = AIMessage(content="", tool_calls=[tc])
    ai_final = AIMessage(content="Ernesto tiene varios repositorios públicos en GitHub.")

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [ai_with_tool, ai_final]

    fake_gh = {
        "ok": True,
        "data": [{"name": "my-project", "stars": 5, "language": "Python"}],
        "error": None,
    }

    with (
        patch("scripts.orchestrator._build_llm", return_value=mock_llm),
        patch("scripts.orchestrator._query_github", return_value=fake_gh),
    ):
        result = run_agent([HumanMessage(content="¿Qué repos tiene Ernesto en GitHub?")])

    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert mock_llm.invoke.call_count == 2


# ── Test 4: continuity — two turns ────────────────────────────────────────────


def test_conversation_continuity():
    """Second turn must see the full accumulated message history from turn one."""
    # Turn 1: ask about experience → simple response, no tools
    mock_llm_1 = MagicMock()
    mock_llm_1.invoke.return_value = AIMessage(content="Ernesto trabajó en SESESP.")

    with patch("scripts.orchestrator._build_llm", return_value=mock_llm_1):
        state1 = run_agent([HumanMessage(content="¿Dónde trabajó Ernesto?")])

    # Turn 2: follow-up reformulation
    mock_llm_2 = MagicMock()
    mock_llm_2.invoke.return_value = AIMessage(
        content="Fue en la Secretaría de Seguridad Pública del Estado de Sonora."
    )

    with patch("scripts.orchestrator._build_llm", return_value=mock_llm_2):
        run_agent([HumanMessage(content="¿Y en qué empresa fue eso?")], state=state1)

    # The messages list passed to the LLM in turn 2 must contain both turns' messages
    invoke_args = mock_llm_2.invoke.call_args[0][0]  # list[BaseMessage] passed to invoke
    human_msgs = [m for m in invoke_args if isinstance(m, HumanMessage)]
    ai_msgs = [m for m in invoke_args if isinstance(m, AIMessage)]

    assert len(human_msgs) >= 2, "Both turns' human messages must be in context"
    assert len(ai_msgs) >= 1, "Turn 1 AI response must be in context"
    assert any("SESESP" in m.content for m in ai_msgs)


# ── Test 5: tool results wrapped in untrusted-data delimiters ─────────────────


def test_tool_results_wrapped_in_untrusted_delimiters():
    """Every ToolMessage inserted into state must be wrapped with <untrusted_external_data>."""
    tc = _tool_call("query_cv_tool", {"question": "experiencia laboral"})
    ai_with_tool = AIMessage(content="", tool_calls=[tc])
    ai_final = AIMessage(content="Ernesto trabajó en SESESP.")

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [ai_with_tool, ai_final]

    fake_cv = [
        {
            "section": "Experiencia Laboral",
            "entry_title": "SESESP",
            "content": "Desarrollador IA en SESESP.",
            "similarity": 0.88,
        }
    ]

    with (
        patch("scripts.orchestrator._build_llm", return_value=mock_llm),
        patch("scripts.orchestrator._query_cv", return_value=fake_cv),
    ):
        result = run_agent([HumanMessage(content="experiencia laboral")])

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) > 0, "At least one ToolMessage must be in final state"
    for tm in tool_messages:
        assert "<untrusted_external_data" in tm.content
        assert "</untrusted_external_data>" in tm.content
