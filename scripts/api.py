"""FastAPI app — POST /v1/responses (Open Responses subset mínimo viable)."""

import logging
import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

from scripts.logging_config import conversation_id_var, setup_logging
from scripts.orchestrator import AgentState, run_agent

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="CV Agent — Open Responses subset")

# In-memory conversation store. Lost on container restart (by design, PRD §7).
_conversations: dict[str, AgentState] = {}

OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
_MAX_INPUT_LEN = 4_000


def _err(msg: str, *, reason: str, **fields) -> JSONResponse:
    logger.warning("request_rejected", extra={"reason": reason, **fields})
    return JSONResponse({"error": {"message": msg}}, status_code=400)


@app.get("/.well-known/agent-card.json")
async def agent_card(request: Request) -> JSONResponse:
    """A2A agent card — describe el agente y apunta al endpoint Open Responses.

    `url` se arma desde el host de la request en vez de hardcodearse, así
    sirve igual en local, docker-compose o el dominio real de Render/GCP.
    """
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "name": "CV Agent — Ernesto Mendieta Cuecuecha",
            "description": (
                "Agente conversacional que responde preguntas sobre la experiencia "
                "laboral, educación, proyectos, habilidades y repositorios públicos "
                "de GitHub de Ernesto Mendieta Cuecuecha, candidato a Ingeniero en IA."
            ),
            "version": "1.0.0",
            "url": f"{base_url}/v1/responses",
            "provider": {"name": "Ernesto Mendieta Cuecuecha"},
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "extendedAgentCard": False,
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {
                    "id": "query-cv",
                    "name": "Consultar CV",
                    "description": (
                        "Responde preguntas sobre experiencia laboral, educación, "
                        "proyectos y habilidades del candidato, basado únicamente "
                        "en el contenido de su CV."
                    ),
                    "tags": ["cv", "experiencia", "educacion"],
                    "examples": ["¿Cuál es la experiencia laboral de Ernesto?"],
                },
                {
                    "id": "query-github",
                    "name": "Consultar GitHub",
                    "description": (
                        "Consulta los repositorios públicos de GitHub del candidato: "
                        "lista de repos, lenguajes, README y actividad reciente."
                    ),
                    "tags": ["github", "repositorios"],
                    "examples": ["¿Qué lenguajes usa más en sus proyectos de GitHub?"],
                },
            ],
            "securitySchemes": [],
            "security": [],
        }
    )


@app.post("/v1/responses")
async def create_response(request: Request) -> JSONResponse:
    start = time.perf_counter()

    try:
        body: dict = await request.json()
    except Exception:  # noqa: BLE001
        return _err("Request body must be valid JSON.", reason="invalid_json")

    if not isinstance(body, dict):
        return _err("Request body must be a JSON object.", reason="bad_shape")

    inp = body.get("input")
    if inp is None or inp == "" or inp == []:
        return _err("'input' is required and must not be empty.", reason="empty_input")

    if isinstance(inp, str) and len(inp) > _MAX_INPUT_LEN:
        return _err(
            f"'input' exceeds the maximum length of {_MAX_INPUT_LEN} characters.",
            reason="input_too_long",
            input_len=len(inp),
        )

    if isinstance(inp, str):
        new_messages = [HumanMessage(content=inp)]
    elif isinstance(inp, list):
        role_map: dict = {"user": HumanMessage, "assistant": AIMessage}
        new_messages = []
        for m in inp:
            if not isinstance(m, dict) or "content" not in m:
                return _err(
                    "Each message in 'input' must have 'role' and 'content'.",
                    reason="bad_shape",
                )
            cls = role_map.get(m.get("role", "user"), HumanMessage)
            new_messages.append(cls(content=m["content"]))
        if not new_messages:
            return _err("'input' array must not be empty.", reason="empty_input")
    else:
        return _err(
            "'input' must be a string or an array of message objects.",
            reason="bad_shape",
        )

    conv_id: str = body.get("conversation_id") or str(uuid.uuid4())
    prior_state = _conversations.get(conv_id)

    token = conversation_id_var.set(conv_id)
    try:
        logger.info(
            "request_received",
            extra={"input_len": len(inp), "is_new_conversation": prior_state is None},
        )
        try:
            new_state = run_agent(new_messages, state=prior_state)
        except Exception:
            logger.exception(
                "request_failed",
                extra={"latency_ms": round((time.perf_counter() - start) * 1000, 1)},
            )
            return JSONResponse(
                {"error": {"message": "Internal error while processing the request."}},
                status_code=500,
            )

        _conversations[conv_id] = new_state

        last = new_state["messages"][-1]
        text: str = last.content if isinstance(last.content, str) else str(last.content)

        logger.info(
            "request_completed",
            extra={
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "total_messages_in_state": len(new_state["messages"]),
                "response_len": len(text),
            },
        )
    finally:
        conversation_id_var.reset(token)

    return JSONResponse(
        {
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "created_at": int(time.time()),
            "model": OPENROUTER_MODEL,
            "conversation_id": conv_id,
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }
    )
