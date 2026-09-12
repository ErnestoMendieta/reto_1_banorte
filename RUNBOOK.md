# Runbook — CV Agent

Guía operativa de un solo archivo: cómo levantar los contenedores, dónde ver
logs, cómo inspeccionar la telemetría (razonamiento del agente), cómo correr
la suite de pruebas y la evaluación end-to-end, y cómo interpretar los
resultados de ambas.

---

## 1. Levantar los contenedores

Requisitos: Docker + Docker Compose, y un archivo `.env` en la raíz del repo
(no está en git) con al menos:

```
GITHUB_TOKEN=...
OPENROUTER_API_KEY=...
CV_TEX_PATH=data/cv.tex
DATABASE_URL=postgresql://cvagent:cvagent@db:5432/cvagent   # sobreescrita por docker-compose para el contenedor app
GITHUB_USERNAMES=...
OPENROUTER_MODEL=openai/gpt-4o-mini
LOG_FORMAT=console   # "console" = legible en terminal local; "json" (default) = una línea JSON por log
```

`docker-compose.yml` define dos servicios:

| Servicio | Imagen/build | Puerto host | Notas |
|---|---|---|---|
| `db`  | `pgvector/pgvector:pg16` | `5433 → 5432` | Postgres con extensión pgvector, volumen persistente `pgdata` |
| `app` | build local (`Dockerfile`) | `8080 → 8080` | FastAPI (`uvicorn main:app`), lee `.env` vía `env_file` |

```bash
# Levantar todo (build de la imagen + arranque de ambos servicios)
docker-compose up --build

# En segundo plano
docker-compose up --build -d

# Ver estado de los contenedores
docker-compose ps

# Apagar (conserva el volumen pgdata, o sea los datos ya ingeridos)
docker-compose down

# Apagar y borrar también los datos de Postgres (reingesta desde cero)
docker-compose down -v
```

**Primera vez / tras `down -v`:** la base de datos arranca vacía. Hay que
correr la ingesta del CV una vez que `db` esté arriba:

```bash
docker-compose exec app python scripts/ingest_cv.py
```

**Verificar que el servicio responde:**

```bash
curl -X POST http://localhost:8080/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```

Una respuesta 200 con `"status": "completed"` confirma que `app` y `db` están
sanos y conectados.

---

## 2. Dónde ver los logs

Los logs van **solo a stdout** (nunca a archivo) — así lo captura tanto
`docker-compose` en local como Cloud Logging en producción
(`scripts/logging_config.py`).

```bash
# Logs de ambos servicios, siguiendo en vivo
docker-compose logs -f

# Solo el servicio de la app (el que importa casi siempre)
docker-compose logs -f app

# Solo Postgres
docker-compose logs -f db

# Últimas N líneas sin seguir
docker-compose logs --tail=200 app
```

### Formato de log

Controlado por `LOG_FORMAT` en `.env`:

- `LOG_FORMAT=json` (default, recomendado para producción/Cloud Run): una
  línea JSON por evento — `timestamp`, `level`, `logger`, `event`,
  `conversation_id`, más los campos extra de cada llamado.
- `LOG_FORMAT=console`: línea legible para desarrollo local, formato:
  `HH:MM:SS.mmm NIV [convid8] logger_name       evento               campo=valor ...`

Para debugging local interactivo, cambia `LOG_FORMAT=console` en `.env` y
reinicia `docker-compose up --build`.

### Correlación por conversación

Todo log de una misma request/conversación comparte `conversation_id` (un
`ContextVar`, ver `scripts/logging_config.py`). Para seguir una conversación
específica end-to-end:

```bash
# json: filtra por el campo conversation_id
docker-compose logs app | grep '"conversation_id": "abc123'

# console: el tag [abc12345] son los primeros 8 caracteres del uuid
docker-compose logs app | grep '\[abc12345\]'
```

### Eventos a buscar

| Evento | Dónde | Qué significa |
|---|---|---|
| `request_received` / `request_completed` / `request_failed` / `request_rejected` | `scripts/api.py` | Ciclo de vida de una request HTTP a `/v1/responses` |
| `llm_call_end` | `scripts/orchestrator.py` | El LLM terminó de generar (con o sin tool calls) |
| `tool_batch_start` / `tool_result_wrapped` / `tool_batch_end` | `scripts/orchestrator.py` | Ejecución de tool calls solicitadas por el LLM |
| `graph_run_summary` | `scripts/orchestrator.py` | Resumen de una corrida completa del grafo LangGraph |
| `model_load` / `query_cv_result` / `query_cv_error` | `scripts/query_cv.py` | Retrieval semántico sobre el CV (pgvector) |
| `query_github_result` / `query_github_rate_limited` / `query_github_network_error` | `scripts/query_github.py` | Llamadas a la API de GitHub |

---

## 3. Ver las respuestas y el razonamiento del agente (telemetría)

Hay tres formas, de menos a más detalle:

### a) Cliente interactivo (solo la respuesta final)

```bash
python scripts/chat_cli.py
# o contra un contenedor ya corriendo:
python scripts/chat_cli.py --url http://localhost:8080/v1/responses
```

Mantiene un mismo `conversation_id` durante toda la sesión. Solo muestra la
respuesta final — no expone tool calls intermedios (la API `/v1/responses`
tampoco los expone, por diseño).

### b) Logs estructurados (el "razonamiento" del agente)

La secuencia `llm_call_end` → `tool_batch_start` → `tool_result_wrapped` (uno
por tool call) → `tool_batch_end` → ... → `graph_run_summary` en los logs de
`app` (sección 2) es la traza real de decisiones del agente: qué tool decidió
llamar, con qué argumentos, y qué resultado obtuvo. Con `LOG_FORMAT=console`
es legible directamente seguiendo `docker-compose logs -f app` mientras se
manda una pregunta desde `chat_cli.py` o `curl`.

### c) Inspección directa del retrieval del CV (sin pasar por el LLM)

```bash
python scripts/inspect_rag.py "¿Cuál es la experiencia laboral de Ernesto?"
python scripts/inspect_rag.py "stack de IA" --top-k 6
```

Muestra cada chunk recuperado de pgvector con su `similarity`, `section`,
`entry_title` y contenido — útil para depurar por qué el agente citó (o no
citó) cierta información del CV, sin gastar tokens de LLM.

### d) Reportes de evaluación (razonamiento + veredicto por caso)

Los JSON en `evaluation/results/eval_<timestamp>.json` (ver sección 5) son la
fuente más completa: por cada caso y cada intento, guardan `tool_calls_seen`
(qué tools llamó y con qué argumentos), `final_answer` (la respuesta
completa), y el veredicto de cada check. Es la telemetría más rica sin tener
que reconstruirla a mano desde logs.

---

## 4. Ejecutar la suite de pruebas (pytest)

`pytest.ini` fija `pythonpath = .`, así que se corre desde la raíz del repo,
sin necesidad de instalar el paquete.

```bash
# Instalar dependencias (si no se usa el contenedor)
pip install -r requirements.txt

# Toda la suite
pytest

# Un archivo
pytest tests/test_orchestrator.py

# Un test puntual, con salida verbose
pytest tests/test_query_github.py -k test_rate_limited -v

# Dentro del contenedor de la app
docker-compose exec app pytest
```

Archivos en `tests/`:

| Archivo | Qué cubre |
|---|---|
| `test_api.py` | Endpoint `/v1/responses` (validación de input, errores, shape de respuesta) |
| `test_orchestrator.py` | Grafo LangGraph — routing entre LLM y tools, manejo de estado |
| `test_query_cv.py` | Retrieval semántico sobre el CV |
| `test_query_github.py` | Cliente de la API de GitHub (éxito, rate limit, errores de red) |
| `test_ingest_cv.py` | Parseo/ingesta del CV a chunks + embeddings |
| `test_evaluation_dataset.py` | Valida el **schema estático** de `evaluation/dataset.json` (sin ejecutar el agente, sin DB, sin red) |

### Cómo interpretar el resultado de pytest

- `pytest` es de unidad/integración **sin costo**: no llama a OpenRouter ni
  usa la DB real (usan mocks/fixtures). Un fallo aquí es un bug de código,
  no un problema de calidad del agente.
- Salida esperada en verde: `N passed in X.XXs`. Cualquier `F` (failed) o `E`
  (error) imprime el traceback justo arriba del resumen — el archivo:línea
  del `assert` que falló es el punto de partida.
- `test_evaluation_dataset.py` fallando indica que `evaluation/dataset.json`
  quedó con un caso mal formado (falta un campo obligatorio, `check_type`
  inválido, etc.) — arréglalo ahí antes de correr `run_eval.py`, porque el
  runner no valida el schema por su cuenta.

---

## 5. Ejecutar y ejecutar/interpretar la evaluación end-to-end (`run_eval.py`)

Esto **no es pytest** — corre el agente real contra `evaluation/dataset.json`
(22 casos), con llamadas reales a OpenRouter (costo) y a la DB. Se invoca a
mano, nunca desde `pytest tests/`.

```bash
# Todo el dataset
python -m evaluation.run_eval

# Solo casos puntuales
python -m evaluation.run_eval --id cv-001 chat-001

# Solo una o más categorías
python -m evaluation.run_eval --category cv_direct github

# Saltar la categoría adversarial (repeat=3 + judge, la más cara)
python -m evaluation.run_eval --skip-adversarial

# Sin LLM-judge (más barato; los casos que lo requieren quedan not_run)
python -m evaluation.run_eval --no-judge

# Verbose: imprime tool calls y respuesta de cada intento en consola
python -m evaluation.run_eval -v
```

Categorías del dataset: `cv_direct`, `github`, `multi_tool`, `continuity`,
`out_of_scope`, `small_talk`, `adversarial` — ver `evaluation/README.md` para
el detalle de qué valida cada una y el schema completo de cada caso.

### Salida en consola

```
[1/22] cv-001 (cv_direct) ... PASS: todos los intentos pasaron
...
=== Resumen ===
  total: 22
  pass: 20
  fail: 1
  error: 0
  not_run: 1
  casos no-pass: ['adv-002', 'adv-003']
```

### Reporte JSON

Cada corrida escribe `evaluation/results/eval_<timestamp>.json` (o la ruta
de `--output`). Contiene, por caso, cada intento con: `tool_calls_seen`
(nombre + args), `tool_calls_ok`/`tool_calls_reason`, `final_answer`,
`content_check` (`keywords`|`judge`|`none`), `content_ok`/`content_reason`,
y `judge_raw` (salida cruda del LLM-judge si aplica).

### Cómo interpretar cada estado

| Status | Significado | Acción |
|---|---|---|
| `pass` | Todos los `repeat` intentos pasaron tool-calls **y** content check | Ninguna |
| `fail` | Al menos un intento falló tool-calls o content check | Revisar `tool_calls_reason` / `content_reason` del intento fallido en el JSON; si es `adversarial`, revisar si el guardrail realmente cedió |
| `error` | Excepción durante la corrida, o el LLM-judge no devolvió JSON parseable | Revisar `error_message`; si es `judge_output_unparseable`, reintentar o inspeccionar `judge_raw` |
| `not_run` | Caso con `runnable_live: false` sin mock registrado, o `--no-judge` deshabilitó un check que lo requería | No cuenta como fallo — está documentado en el reporte, no ejecutado |

Notas importantes de diseño (ver `evaluation/README.md` y el docstring de
`run_eval.py`):

- Los `check_type` de tipo `refusal`, `adversarial_guardrail` y
  `graceful_degradation` usan **LLM-judge** (reutiliza `OPENROUTER_MODEL`) —
  un modelo evaluándose a sí mismo puede ser indulgente; no es apto para
  evaluación de producción sin separar el modelo del judge.
- Los casos `adversarial` tienen `repeat: 3` por el no-determinismo del LLM;
  **todas** las corridas deben pasar para que el caso cuente como `pass`.
- `adv-003` es el único caso con `runnable_live: false` — requiere mockear
  `scripts.orchestrator._query_github` (ya está resuelto en `MOCK_REGISTRY`
  dentro de `run_eval.py`, no necesita configuración manual).

---

## 6. Referencia rápida de comandos

```bash
# Levantar / bajar
docker-compose up --build [-d]
docker-compose down [-v]

# Ingesta inicial del CV (una vez, tras primer arranque o down -v)
docker-compose exec app python scripts/ingest_cv.py

# Logs
docker-compose logs -f app
docker-compose logs -f db

# Probar el endpoint
curl -X POST http://localhost:8080/v1/responses -H "Content-Type: application/json" -d '{"input": "..."}'

# Chat interactivo
python scripts/chat_cli.py

# Inspeccionar retrieval del CV sin LLM
python scripts/inspect_rag.py "pregunta" --top-k 4

# Pruebas unitarias (rápidas, sin costo)
pytest

# Evaluación end-to-end (llamadas reales a OpenRouter, con costo)
python -m evaluation.run_eval [--id ...] [--category ...] [--skip-adversarial] [--no-judge] [-v]
```
