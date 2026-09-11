# AGENT.md — Instrucciones operacionales del loop

Eres el agente que implementa el **agente conversacional de CV (reto Banorte)**
una user story por iteración. Lee esto, `../reto-banorte-cv-agent-PRD.md`, y la
spec correspondiente en `../specs/` antes de tocar nada.

## Stack

- Python 3.12, FastAPI (endpoint), LangGraph (orquestador), Postgres +
  pgvector (RAG), OpenRouter (LLM vía HTTP), GitHub REST API v3.
- Gestión de dependencias: `requirements.txt` en la raíz.
- Tests: `pytest`. Lint: `ruff check .`.

## Cómo levantarlo

- **DB**: `docker-compose up db` → Postgres+pgvector en `localhost:5432`
  (ver `../specs/07-deploy-docker-cloudrun.md` para el `docker-compose.yml`).
- **Ingesta del CV** (una vez que exista `scripts/ingest_cv.py`, US-001):
  `python scripts/ingest_cv.py`.
- **App**: `uvicorn main:app --reload --port 8080` (una vez exista, US-005).
- **Todo junto**: `docker-compose up`.

## Comandos de validación (EXACTOS)

- Siempre, si tocaste código Python:
  ```
  ruff check .
  pytest
  ```
  Ambos deben pasar sin errores antes de commitear.
- Si tocaste `Dockerfile`/`docker-compose.yml` (US-007):
  ```
  docker build -t cv-agent .
  docker-compose up -d && curl -s localhost:8080/v1/responses -X POST -d "{\"input\":\"hola\"}" -H "Content-Type: application/json"
  docker-compose down
  ```

## Convenciones críticas que DEBES respetar

1. **Una story por iteración.** Commit atómico por story. No adelantes trabajo
   de una story posterior aunque sea tentador (p.ej. no metas guardrails de
   US-006 mientras implementas US-002).
2. **Sigue el orden de `priority` en `prd.json`.** Las stories tienen
   dependencias reales entre sí (01→07 en `../specs/README.md`) — no saltes
   una story pendiente para hacer una posterior.
3. **No inventes el checkpoint exacto de `EMBEDDING_MODEL`** ni la estructura
   de macros del `.tex` sin antes verificar el archivo real en el repo (ver
   "Abierto / bloqueado" en `../specs/01-db-schema-ingestion.md`). Si el
   archivo `.tex` del CV no existe todavía en el repo, anótalo en
   `progress.txt` y usa un `.tex` de ejemplo mínimo para no bloquear el resto
   del desarrollo, dejando claro en `notes` que es un fixture temporal.
4. **Nunca commitees `.env`** (ya existe con `GITHUB_TOKEN` y
   `OPENROUTER_API_KEY` reales).
5. **No inventes datos del candidato.** Cualquier respuesta del agente debe
   provenir de `query_cv`/`query_github` — esto se valida explícitamente en
   US-004 y US-006, pero aplica a todo el desarrollo.
6. **Guardrails de US-006 no son opcionales** — están en el MVP (ver PRD §2),
   no se pueden posponer indefinidamente una vez llegue su turno.
7. **US-007 (deploy real a Cloud Run) puede quedar parcialmente bloqueado**:
   no hay proyecto de GCP creado todavía. Implementa y valida todo lo que no
   dependa de GCP (docker-compose local, Dockerfile, `DEPLOY.md` con los
   comandos `gcloud` listos); marca explícitamente en `notes` qué quedó
   pendiente de ejecución real por falta del proyecto.
8. **Reutiliza lo que ya exista en el repo antes de crear algo nuevo** — busca
   con Grep/Glob antes de asumir que un módulo/función no existe.

## Archivos críticos a LEER antes de modificar

- `../reto-banorte-cv-agent-PRD.md` — contexto y decisiones de producto.
- `../specs/README.md` — orden de build y bloqueos activos.
- `../specs/0N-*.md` — la spec exacta de la story que vas a implementar.
- `progress.txt` — sección "Codebase Patterns" primero.
- `.env` — variables ya disponibles (no lo leas completo si no es necesario,
  solo confirma qué claves existen).

## Definición de "hecho" por iteración

1. El código del story implementado, siguiendo el contrato exacto de la spec
   correspondiente (schemas, nombres de función, shapes de request/response).
2. `ruff check .` y `pytest` pasan (o los comandos de Docker si aplica, ver
   arriba).
3. `prd.json` actualizado: el story con `"passes": true` y `notes` con un
   resumen breve de lo implementado (y cualquier bloqueo/limitación real).
4. `../specs/README.md` actualizado: la fila de esa spec en la tabla de
   estado pasa a `hecho`.
5. Append a `progress.txt`: qué se hizo, archivos tocados, patrones nuevos
   descubiertos en la codebase.
6. Commit: `feat: [US-XXX] - <título de la story>`.
