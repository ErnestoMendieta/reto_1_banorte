# PRD — Agente conversacional de CV (Reto IA Banorte)

## 1. Contexto y objetivo

Reto de Banorte: construir y **desplegar** un agente de IA que converse
naturalmente sobre el CV del candidato (perfil profesional, experiencia,
habilidades, proyectos), demostrando criterio de ingeniería — no es una
checklist obligatoria, la profundidad técnica debe justificarse por el
problema y las decisiones de arquitectura, no por cubrir todas las áreas
sugeridas.

Áreas que el reto invita a explorar (no todas obligatorias): diseño
conversacional con contexto, integración de modelos/protocolos/herramientas,
arquitecturas distribuidas (contenedores, serverless, DB, colas,
observabilidad), sistemas agénticos (tools, MCP, colaboración entre
agentes), guardrails/evaluación/seguridad, despliegue y operación confiable.
Menciona explícitamente Open Responses, A2A y A2UI como conceptos posibles.

## 2. Alcance

### MVP (obligatorio para este PRD)

- Orquestador agéntico en **LangGraph** con subagentes/tools.
- **Tool 1 — `query_cv`**: RAG sobre el CV vectorizado (Postgres + pgvector,
  embeddings con Qwen local 2–3B).
- **Tool 2 — `query_github`**: subagente que consulta la GitHub API
  (repos, lenguajes, README, actividad) del candidato.
- **Compatibilidad con Open Responses (subset mínimo viable)**: `POST
  /v1/responses` aceptando input de texto (simple o array de items
  `role`+`content`) y devolviendo el shape estándar (`id`, `object:
  "response"`, `output: [{type:"message", role:"assistant",
  content:[{type:"output_text", text}]}]`, `status`). Sin streaming SSE,
  sin inputs multimodales, sin `tools` expuestos al cliente (las tools son
  internas al grafo de LangGraph), sin `GET /responses/{id}`. Estado de
  conversación entre turnos: in-memory en el proceso del orquestador (no
  se persiste `previous_response_id` en Postgres) — suficiente para la
  demo/evaluación, se documenta como limitación conocida.
- **Deploy**: contenedor Docker corriendo en Cloud Run (no solo local).
- **Guardrail anti-prompt-injection**: dado que el agente representa
  públicamente al candidato, es obligatorio, no opcional. Alcance mínimo:
  (a) system prompt que fija rol/límites explícitamente; (b) todo el
  contenido devuelto por `query_cv` y `query_github` se envuelve como
  datos delimitados, con instrucción explícita al LLM de ignorar cualquier
  instrucción contenida ahí dentro — el vector más realista es un README
  de GitHub con texto inyectado, no solo el input del usuario; (c)
  guardrail de salida alineado con el NFR de §5 (no inventar información
  fuera de lo recuperado).

### Nice-to-have (si alcanza el tiempo, no bloquea el MVP)

- Suite de evaluación con LangSmith (casos de prueba + métricas, al estilo
  de los evals de ElevenLabs).
- Observabilidad (logging estructurado, tracing).
- A2A / A2UI, si el tiempo lo permite.
- Persistencia de estado de conversación en Postgres (continuidad real
  entre despliegues, en vez de in-memory).

### Fuera de alcance

- Fine-tuning de modelos.
- Autenticación multi-usuario / multi-tenancy.
- UI custom (el foco es el agente/backend, no una interfaz visual).
- Fuentes más allá de CV + GitHub (LinkedIn, portafolio web, etc.).

## 3. Usuario y caso de uso

Usuario: reclutador o evaluador técnico de Banorte que conversa con el
agente para conocer la trayectoria del candidato — experiencia, skills,
proyectos, y detalles de su código en GitHub (qué hace un repo, qué stack
usa, actividad reciente).

## 4. Arquitectura propuesta

```
Cliente (compatible Open Responses)
  └── API HTTP (contrato Open Responses)
        └── LangGraph orchestrator
              ├── router node → decide qué tool usar
              ├── tool: query_cv  → retrieval semántico (pgvector)
              └── tool: query_github → GitHub REST/GraphQL API
LLM orquestador: vía OpenRouter, modelo configurable por env var
  (default: tier "mini/flash" — ver §7)
Embeddings: Qwen local (2–3B) → Postgres + pgvector
Ingesta CV: parseo directo del .tex fuente (por \section{}), no del PDF
  renderizado — chunk por sección, y por entrada individual dentro de
  Experiencia/Proyectos
Deploy:
  - Local/dev: docker-compose con 2 contenedores — `db`
    (pgvector/pgvector:pg16, con volume para persistencia) y `app`
    (LangGraph orchestrator + endpoint Open Responses), env vars vía .env
    (GITHUB_TOKEN, OPENROUTER_API_KEY).
  - Producción: solo el contenedor `app` se despliega a Cloud Run —
    Cloud Run es stateless/efímero (sin disco persistente, escala a cero,
    múltiples réplicas), no apto para hostear la DB. Postgres pasa a ser
    **Cloud SQL for PostgreSQL** (managed, soporta pgvector), conectado
    desde `app` vía Cloud SQL Auth Proxy o IP privada. La lógica de la
    app no cambia, solo el connection string de la DB.
```

## 5. Requisitos no funcionales

- Respuestas consistentes ante reformulaciones de la misma pregunta
  (mantener contexto del perfil).
- Guardrail mínimo: no inventar información que no esté en el CV o en los
  repos consultados.
- Reproducible: Dockerfile + variables de entorno documentadas, deploy
  repetible sin pasos manuales ocultos.

## 6. Entregables esperados

- Código fuente del agente.
- `docker-compose.yml` (db + app) para desarrollo/pruebas local.
- Dockerfile del `app` + instrucciones de deploy a Cloud Run (conectado a
  Cloud SQL for PostgreSQL en producción, ver §4).
- Documentación breve de arquitectura y decisiones (para justificar
  criterio técnico, como pide el reto).
- (Nice-to-have) Suite de evals en LangSmith con métricas.

## 7. Decisiones tomadas

- **LLM orquestador vía OpenRouter**: no se fija un único modelo — se deja
  configurable por variable de entorno para mantener la arquitectura
  agnóstica de proveedor (ventaja de usar OpenRouter, justificable ante el
  evaluador). Default de arranque: nivel "mini/flash" (p. ej. GPT-5 mini o
  equivalente Gemini Flash de la familia disponible al momento de
  implementar), con ambos requisitos de soporte de tools/function calling.
  Se escala a un modelo mayor (GPT-5 full / Gemini Pro) solo si en pruebas
  el modelo default falla enrutando entre `query_cv`/`query_github` o
  pierde contexto en reformulaciones.
- **Alcance de Open Responses**: subset mínimo viable (ver detalle en §2,
  MVP). No contrato completo.
- **Chunking del CV**: por sección (parseado del `.tex` fuente vía
  `\section{}`), con sub-chunking por entrada individual dentro de
  Experiencia/Proyectos. CV es de 2 páginas formato Harvard en LaTeX, fuente
  disponible directamente — no se extrae texto del PDF renderizado.
- **Guardrails de seguridad**: capa anti-prompt-injection es obligatoria
  (movida a MVP, ver §2) — el agente representa públicamente al candidato,
  y el vector más realista es contenido inyectado en READMEs/repos de
  GitHub consumidos por `query_github`, no solo el input del usuario.
- **Estado de conversación**: in-memory en el proceso del orquestador para
  el MVP (sin persistencia de `previous_response_id`); persistencia en
  Postgres queda como nice-to-have.

- **OpenRouter vs GCP**: no son alternativas, son piezas independientes.
  OpenRouter resuelve "a qué LLM le hablo" (gateway multimodelo con una
  sola API key); GCP/Cloud Run resuelve "dónde vive el proceso" — el
  contenedor que expone `/v1/responses`, corre LangGraph, consulta
  Postgres y llama a la API de GitHub, y que **desde ahí** hace la llamada
  saliente a OpenRouter. El requisito de Cloud Run (§2, MVP) es
  independiente de qué LLM se use.
- **API de GitHub**: REST v3 sobre HTTPS, autenticada con Personal Access
  Token (`Authorization: Bearer <token>`) — sin token el rate limit es de
  60 req/hora por IP, con token 5,000 req/hora (necesario para no
  arriesgar un rate-limit a media demo). Endpoints a usar en
  `query_github`: `GET /users/{username}/repos` (lista de repos),
  `GET /repos/{owner}/{repo}` (detalle), `GET
  /repos/{owner}/{repo}/languages` (breakdown de lenguajes), `GET
  /repos/{owner}/{repo}/readme` (contenido en base64, hay que
  decodificarlo), `GET /repos/{owner}/{repo}/commits` (actividad
  reciente). El contenido de READMEs se trata como dato no confiable
  dentro del guardrail anti-injection (puede contener texto de terceros).

## 7bis. Preguntas abiertas restantes

- Confirmar cuenta/API key de OpenRouter y proyecto de GCP (billing) ya
  provisionados antes de generar specs de deploy.
- **Alcance de `query_github`** (qué repos consulta): pendiente, se
  definirá en un `.txt` con links que el usuario proveerá más adelante —
  bloqueante solo para la spec final de esta tool, no para arrancar el
  resto del build.

## 8. Criterios de éxito

- El agente conversa naturalmente y mantiene contexto sobre el perfil.
- Arquitectura agéntica (tools/subagentes) justificada, no decorativa.
- Integración de Open Responses funcionando end-to-end.
- Desplegado y operable de forma confiable (Cloud Run, no solo `localhost`).
- Decisiones técnicas documentadas y defendibles ante el evaluador.
