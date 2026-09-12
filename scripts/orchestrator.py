"""Orchestrator — LangGraph agent/tools graph for the CV conversational agent."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()

from scripts.logging_config import setup_logging
from scripts.query_cv import query_cv as _query_cv
from scripts.query_github import query_github as _query_github

setup_logging()
logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

CANDIDATE_NAME = "Ernesto Mendieta Cuecuecha"

_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt"
SYSTEM_PROMPT = (_PROMPT_DIR / "system_prompt.md").read_text(encoding="utf-8").format(
    candidate_name=CANDIDATE_NAME
)


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


@tool
def query_cv_tool(question: str, top_k: int = 4) -> str:
    """Busca información en el CV del candidato (experiencia, educación, skills, proyectos) relevante a una pregunta."""
    results = _query_cv(question, top_k)
    return json.dumps(results, ensure_ascii=False)


@tool
def query_github_tool(
    aspect: Literal["list_repos", "repo_overview", "languages", "readme", "activity"],
    repo_name: str | None = None,
) -> str:
    """Consulta los repositorios públicos de GitHub del candidato: lista de repos, lenguajes, README o actividad reciente."""
    result = _query_github(aspect, repo_name)
    return json.dumps(result, ensure_ascii=False)


_TOOLS = [query_cv_tool, query_github_tool]
_TOOL_NODE = ToolNode(_TOOLS)


def _build_llm():
    return ChatOpenAI(
        model=OPENROUTER_MODEL,
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        max_tokens=1024,
    ).bind_tools(_TOOLS)


def _agent_node(state: AgentState, llm) -> dict:
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(state["messages"])
    start = time.perf_counter()
    response = llm.invoke(messages)
    tool_calls = getattr(response, "tool_calls", None) or []
    logger.info(
        "llm_call_end",
        extra={
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "decided_tools": [{"name": tc["name"], "args": tc["args"]} for tc in tool_calls],
        },
    )
    return {"messages": [response]}


def _tools_node(state: AgentState) -> dict:
    """Execute tools and wrap each result in untrusted-data delimiters."""
    requested = getattr(state["messages"][-1], "tool_calls", None) or []
    logger.info(
        "tool_batch_start",
        extra={"tool_calls": [{"name": tc["name"], "args": tc["args"]} for tc in requested]},
    )
    start = time.perf_counter()
    result = _TOOL_NODE.invoke(state)

    wrapped = []
    for msg in result.get("messages", []):
        if isinstance(msg, ToolMessage):
            source = msg.name or "tool"
            content = (
                f'<untrusted_external_data source="{source}">\n'
                f"{msg.content}\n"
                f"</untrusted_external_data>"
            )
            logger.info(
                "tool_result_wrapped",
                extra={
                    "tool_name": source,
                    "tool_call_id": msg.tool_call_id,
                    "result_len": len(msg.content or ""),
                },
            )
            wrapped.append(
                ToolMessage(content=content, tool_call_id=msg.tool_call_id, name=msg.name)
            )
        else:
            wrapped.append(msg)

    logger.info(
        "tool_batch_end",
        extra={"latency_ms": round((time.perf_counter() - start) * 1000, 1), "count": len(wrapped)},
    )
    return {"messages": wrapped}


def _build_graph(llm):
    def agent_node(state):
        return _agent_node(state, llm)

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", _tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", tools_condition)
    g.add_edge("tools", "agent")
    return g.compile()


def run_agent(
    messages: list[BaseMessage],
    state: AgentState | None = None,
) -> AgentState:
    """Run the CV agent, optionally continuing from a prior conversation state."""
    llm = _build_llm()
    graph = _build_graph(llm)
    prior: list[BaseMessage] = list(state["messages"]) if state else []
    start = time.perf_counter()
    result = graph.invoke({"messages": prior + list(messages)})

    new_messages = result["messages"][len(prior) + len(messages) :]
    logger.info(
        "graph_run_summary",
        extra={
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "llm_calls": sum(1 for m in new_messages if isinstance(m, AIMessage)),
            "tool_calls": sum(1 for m in new_messages if isinstance(m, ToolMessage)),
        },
    )
    return result
