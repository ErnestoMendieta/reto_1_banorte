# Spec 07 — docker-compose local + Dockerfile + deploy Cloud Run/Supabase

## Objetivo

Contenedorizar la app para desarrollo local (2 contenedores: `db` + `app`)
y dejar el pipeline de deploy a producción documentado y ejecutable, según
lo definido en PRD §4/§6.

**Historial de cambios de plataforma:**
- (2026-09-12, primer cambio) Cloud Run + Cloud SQL → **Render + Supabase**,
  para evitar el costo de Cloud SQL (~$9 USD/mes, sin free tier).
- (2026-09-12, segundo cambio) **Render + Supabase → Cloud Run + Supabase**.
  Render free tier (512MB RAM) no alcanza para cargar `sentence-transformers`
  /torch en `query_cv` — el proceso moría por OOM a media petición (502) en
  cuanto una pregunta real disparaba el tool call (verificado en producción,
  ver "Abierto / bloqueado"). Cloud Run permite `--memory 1Gi` sin costo
  mientras el tráfico quede dentro del free tier (2M requests/mes); ya no
  se usa Cloud SQL (la DB vive en Supabase), que era lo único que cobraba
  en el plan original. Cero cambios al `Dockerfile`.

## Dependencias

- Specs 01–06 implementadas y funcionando localmente sin Docker (o con
  Docker parcial) antes de envolver todo — este es el último paso del
  build.

## Contrato concreto

### `docker-compose.yml` (local/dev)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: cvagent
      POSTGRES_USER: cvagent
      POSTGRES_PASSWORD: cvagent
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  app:
    build: .
    depends_on:
      - db
    env_file: .env
    environment:
      DATABASE_URL: postgresql://cvagent:cvagent@db:5432/cvagent
    ports:
      - "8080:8080"

volumes:
  pgdata:
```

`.env` (ya existe con `GITHUB_TOKEN`, `OPENROUTER_API_KEY`) debe además
tener `GITHUB_USERNAME`, `OPENROUTER_MODEL`, `EMBEDDING_MODEL`,
`EMBEDDING_DIM`, `CV_TEX_PATH` — consolidar ahí todas las env vars usadas
por specs 01-06.

### `Dockerfile` (solo `app`)

Multi-stage, imagen final ligera:

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

(Ajustar nombre del módulo/app real de FastAPI al implementar spec 05.)

### Deploy a producción (Cloud Run + Supabase)

Repo ya en GitHub (`ErnestoMendieta/reto_1_banorte`). Requiere `gcloud` CLI
autenticado y un proyecto de GCP con billing habilitado (para activar la
API de Cloud Run — no implica cobro si el uso queda dentro del free tier).

1. **Supabase** (Postgres + pgvector) — ya provisionado:
   - `create extension if not exists vector;` desde el SQL editor.
   - Ingesta ya corrida una vez desde local apuntando `DATABASE_URL` a
     Supabase: `python scripts/ingest_cv.py`.
2. **Cloud Run** (app):
   ```bash
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com
   gcloud run deploy cv-agent \
     --source . \
     --region {region} \
     --memory 1Gi \
     --allow-unauthenticated \
     --set-env-vars OPENROUTER_MODEL=google/gemini-3.6-flash,GITHUB_USERNAMES=ErnestoMendieta,ErnestoMCUpiit \
     --set-env-vars DATABASE_URL="postgresql://postgres:{tu-password}@db.{project-ref}.supabase.co:5432/postgres" \
     --set-env-vars OPENROUTER_API_KEY={tu-key},GITHUB_TOKEN={tu-token}
   ```
   `--source .` hace build (Cloud Build, usa el `Dockerfile` del repo tal
   cual) + deploy en un solo comando — no hace falta Artifact Registry
   manual. `--memory 1Gi` es el flag crítico: el default de Cloud Run es
   512MB, la misma memoria que causó el OOM en Render.
3. **Verificar**: `curl -X POST https://<servicio>.run.app/v1/responses
   -H "Content-Type: application/json" -d '{"input": "..."}'`.

## Fuera de alcance

- CI/CD automatizado (GitHub Actions, Cloud Build triggers) — deploy
  manual vía `gcloud run deploy` es suficiente para el reto.
- Autoscaling tuning más allá de los defaults de Cloud Run.
- VPC connector / red privada (no hay requisito de aislamiento de red).

## Criterios de aceptación

- [x] `docker-compose up` levanta `db` + `app`, y `curl
      localhost:8080/v1/responses` responde correctamente (mismo criterio
      que spec 05, pero corriendo dentro de Docker).
- [x] La imagen de `app` se construye sin errores (`docker build .`).
- [ ] El servicio desplegado en Cloud Run responde igual que en local
      contra la DB de Supabase, incluyendo preguntas reales que disparan
      `query_cv_tool` (no solo un input trivial) — esto es lo que reveló
      el OOM en Render, hay que probarlo explícitamente, no basta un
      smoke test superficial.

## Abierto / bloqueado

- **Cloud Run escala a cero sin tráfico** (default) → cold start en la
  primera request tras inactividad, igual que pasaba en Render. Aceptable
  para evaluación del reto; `--min-instances 1` lo evita pero deja de ser
  gratis.
- **Incidente registrado**: el deploy en Render (free tier, 512MB RAM)
  causó un crash por OOM en cuanto una pregunta real invocaba
  `query_cv_tool` (carga de `sentence-transformers`/torch) — 502 a medio
  request, contenedor reiniciado. Ver `DEPLOY.md` para el detalle. Por
  esto se migró a Cloud Run con `--memory 1Gi`.
