# Specs — Agente conversacional de CV (Reto Banorte)

Descomposición del PRD (`../reto-banorte-cv-agent-PRD.md`) en specs
ejecutables para el Ralph loop. Cada archivo es una unidad de trabajo
autocontenida: objetivo, contrato concreto, criterios de aceptación
verificables. El loop debe implementarlas en este orden — cada una depende
de que la anterior exista y funcione.

## Orden de build

| # | Spec | Depende de | Estado |
|---|------|-----------|--------|
| 01 | [db-schema-ingestion](01-db-schema-ingestion.md) | — | pendiente |
| 02 | [tool-query-cv](02-tool-query-cv.md) | 01 | pendiente |
| 03 | [tool-query-github](03-tool-query-github.md) | — | pendiente |
| 04 | [orchestrator-langgraph](04-orchestrator-langgraph.md) | 02, 03 | pendiente |
| 05 | [api-open-responses](05-api-open-responses.md) | 04 | pendiente |
| 06 | [guardrails](06-guardrails.md) | 04, 05 | pendiente |
| 07 | [deploy-docker-cloudrun](07-deploy-docker-cloudrun.md) | 01–06 | pendiente |

Actualiza la columna "Estado" (`pendiente` / `en progreso` / `hecho`) a
medida que el loop cierra cada spec — es la señal que el propio loop puede
leer para saber qué sigue.

## Bloqueos externos activos (no bloquean empezar, sí bloquean cerrar specs puntuales)

- **`query_github` (spec 03)**: alcance exacto de repos a consultar pendiente
  de un `.txt` con links que el usuario proveerá. Hasta entonces, default =
  todos los repos públicos de `GITHUB_USERNAME`.
- **Ingesta del CV (spec 01)**: la estructura exacta de macros LaTeX del
  `.tex` fuente aún no se ha inspeccionado — el parser debe ajustarse al
  archivo real una vez esté disponible en el repo.
- **Deploy a Cloud Run (spec 07)**: no hay proyecto de GCP creado todavía.
  El código/scripts de deploy se escriben igual, pero la ejecución real
  (`gcloud run deploy`) queda bloqueada hasta que exista el proyecto.

## Convenciones para todas las specs

- Variables de entorno se leen de `.env` en local (ya contiene
  `GITHUB_TOKEN` y `OPENROUTER_API_KEY`); en Cloud Run se inyectan vía
  Secret Manager (ver spec 07).
- Stack asumido: Python (LangGraph es Python-nativo). Si el loop decide
  otro lenguaje, debe actualizar esta nota y todas las specs afectadas.
- Ninguna spec debe inventar datos del candidato fuera de lo que
  `query_cv`/`query_github` devuelvan — esto es un requisito transversal
  (ver PRD §5 y spec 06).
