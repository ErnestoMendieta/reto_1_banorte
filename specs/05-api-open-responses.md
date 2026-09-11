# Spec 05 — Endpoint Open Responses (subset mínimo viable)

## Objetivo

Exponer el orquestador (spec 04) vía un endpoint HTTP que respeta el
subset mínimo viable del contrato de la OpenAI Responses API (ver PRD §2
y §7), para que cualquier cliente compatible pueda conversar con el
agente.

## Dependencias

- Spec 04 (orquestador).

## Contrato concreto

### Stack asumido

Python + FastAPI (LangGraph es Python-nativo, FastAPI es el default
razonable para exponer HTTP async). Si se cambia, actualizar esta nota y
`specs/README.md`.

### Endpoint

`POST /v1/responses`

**Request** (subset — se ignoran/rechazan campos fuera de este subset):

```json
{
  "model": "string, opcional — informativo, el modelo real lo define OPENROUTER_MODEL en el server",
  "input": "string simple, o array de {role: 'user'|'assistant'|'system', content: string}",
  "conversation_id": "string opcional — identifica una conversación existente para continuidad in-memory"
}
```

**Response** (200):

```json
{
  "id": "resp_<uuid>",
  "object": "response",
  "created_at": 1234567890,
  "model": "<modelo real usado>",
  "conversation_id": "<mismo id recibido, o uno nuevo generado si no vino>",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [
        { "type": "output_text", "text": "<respuesta del agente>" }
      ]
    }
  ]
}
```

**Errores**: HTTP 400 con `{"error": {"message": "..."}}` para input
inválido (p.ej. `input` ausente o vacío).

### Continuidad de conversación (in-memory, ver PRD §7)

- Mantener un diccionario en memoria del proceso:
  `conversations: dict[str, AgentState]`.
- Si el request trae `conversation_id` y existe en el dict, se recupera el
  `AgentState` previo y se le agrega el nuevo mensaje antes de llamar a
  `run_agent`.
- Si no trae `conversation_id`, o no existe, se genera uno nuevo
  (`uuid4`) y se crea un `AgentState` vacío.
- **Limitación conocida y documentada**: si el contenedor se reinicia,
  todas las conversaciones en curso se pierden (no hay persistencia a
  Postgres — decisión tomada en PRD §7, nice-to-have para más adelante).

### Explícitamente fuera de este subset (no implementar)

- Streaming SSE.
- Inputs multimodales (imágenes, archivos, audio).
- Campo `tools` en el request (las tools son internas al grafo, no se
  exponen al cliente).
- `GET /v1/responses/{id}` (recuperar una respuesta pasada por id).
- `background`, `reasoning`, `previous_response_id` con semántica completa
  de la API real (se reemplaza por el `conversation_id` simplificado de
  arriba).

## Criterios de aceptación

- [ ] `curl -X POST /v1/responses -d '{"input": "hola"}'` devuelve un JSON
      con el shape exacto de arriba y `status: "completed"`.
- [ ] Dos requests consecutivos con el mismo `conversation_id` mantienen
      contexto (verificable con una reformulación, igual que en spec 04).
- [ ] Un request sin `input` devuelve 400 con el shape de error definido.
- [ ] Un request con un campo fuera del subset (p.ej. `stream: true`) no
      rompe el servidor — se ignora o se rechaza con 400, a decidir en
      implementación, pero nunca un 500.

## Abierto / bloqueado

Ninguno — depende solo de que spec 04 esté cerrada.
