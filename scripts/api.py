"""FastAPI app — POST /v1/responses (Open Responses subset mínimo viable)."""

import os
import time
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langchain_core.messages import AIMessage, HumanMessage

load_dotenv()

from scripts.orchestrator import AgentState, run_agent

app = FastAPI(title="CV Agent — Open Responses subset")

# In-memory conversation store. Lost on container restart (by design, PRD §7).
_conversations: dict[str, AgentState] = {}

OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
_MAX_INPUT_LEN = 4_000


def _err(msg: str) -> JSONResponse:
    return JSONResponse({"error": {"message": msg}}, status_code=400)


@app.post("/v1/responses")
async def create_response(request: Request) -> JSONResponse:
    try:
        body: dict = await request.json()
    except Exception:  # noqa: BLE001
        return _err("Request body must be valid JSON.")

    if not isinstance(body, dict):
        return _err("Request body must be a JSON object.")

    inp = body.get("input")
    if inp is None or inp == "" or inp == []:
        return _err("'input' is required and must not be empty.")

    if isinstance(inp, str) and len(inp) > _MAX_INPUT_LEN:
        return _err(f"'input' exceeds the maximum length of {_MAX_INPUT_LEN} characters.")

    if isinstance(inp, str):
        new_messages = [HumanMessage(content=inp)]
    elif isinstance(inp, list):
        role_map: dict = {"user": HumanMessage, "assistant": AIMessage}
        new_messages = []
        for m in inp:
            if not isinstance(m, dict) or "content" not in m:
                return _err("Each message in 'input' must have 'role' and 'content'.")
            cls = role_map.get(m.get("role", "user"), HumanMessage)
            new_messages.append(cls(content=m["content"]))
        if not new_messages:
            return _err("'input' array must not be empty.")
    else:
        return _err("'input' must be a string or an array of message objects.")

    conv_id: str = body.get("conversation_id") or str(uuid.uuid4())
    prior_state = _conversations.get(conv_id)

    new_state = run_agent(new_messages, state=prior_state)
    _conversations[conv_id] = new_state

    last = new_state["messages"][-1]
    text: str = last.content if isinstance(last.content, str) else str(last.content)

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
