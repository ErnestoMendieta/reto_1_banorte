# Spec 07 — docker-compose local + Dockerfile + deploy Render/Supabase

## Objetivo

Contenedorizar la app para desarrollo local (2 contenedores: `db` + `app`)
y dejar el pipeline de deploy a producción documentado y ejecutable, según
lo definido en PRD §4/§6.

**Historial de cambios de plataforma:**
- (2026-09-12, cambio 1) Cloud Run + Cloud SQL → **Render + Supabase**,
  para evitar el costo de Cloud SQL (~$9 USD/mes, sin free tier).
- (2026-09-12, cambio 2) **Render + Supabase → Cloud Run + Supabase**.
  Render free tier (512MB RAM) no alcanzaba para cargar
  `sentence-transformers`/torch en `query_cv` — el proceso moría por OOM a
  media petición (502) en cuanto una pregunta real disparaba el tool call
  (verificado en producción). GCP resultó pedir un cargo de tarjeta (~500
  MXN) para verificación de cuenta, inaceptable para el alcance del reto.
- (2026-09-12, cambio 3, **definitivo**) **Cloud Run → de vuelta a Render**.
  La causa real del OOM no era "poca RAM en general", era cargar un modelo
  de embeddings local (torch) en el contenedor. Se movió el cálculo de
  embeddings a la API de OpenRouter (`google/gemini-embedding-2`,
  `scripts/query_cv.py`/`scripts/ingest_cv.py`) — el contenedor ya no carga
  ningún modelo pesado, `sentence-transformers` se quitó de
  `requirements.txt`, y el free tier de Render (512MB) vuelve a alcanzar.
  Esto resuelve el problema de raíz sin pagar Render Starter ni usar GCP.
  Cero cambios al `Dockerfile`.

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

### Deploy a producción (Render + Supabase)

Repo ya en GitHub (`ErnestoMendieta/reto_1_banorte`), deploy conectado
directo desde ahí. Ambos con free tier permanente, sin tarjeta/billing.

1. **Supabase** (Postgres + pgvector) — ya provisionado:
   - `create extension if not exists vector;` desde el SQL editor.
   - Ingesta corrida desde local apuntando `DATABASE_URL` a Supabase:
     `python scripts/ingest_cv.py` (embeddings vía OpenRouter
     `google/gemini-embedding-2`, 768 dims — ver `DEPLOY.md` si migras
     desde la tabla vieja de `sentence-transformers`, dim distinta).
2. **Render** (app, Web Service):
   - "New Web Service" → conectar el repo de GitHub → Environment:
     Docker (usa el `Dockerfile` tal cual, sin cambios).
   - Variables de entorno: `GITHUB_TOKEN`, `GITHUB_USERNAMES`,
     `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `CV_TEX_PATH`, y
     `DATABASE_URL` apuntando a Supabase. No hace falta `EMBEDDING_MODEL`/
     `EMBEDDING_DIM` (los defaults del código ya coinciden con la ingesta).
   - Puerto: Render detecta `EXPOSE 8080` del Dockerfile automáticamente.
3. **Verificar**: `curl -X POST https://<servicio>.onrender.com/v1/responses
   -H "Content-Type: application/json" -d '{"input": "..."}'` — probar con
   una pregunta real que dispare `query_cv_tool`, no solo un input trivial
   (así fue como apareció el OOM la primera vez).

## Fuera de alcance

- CI/CD automatizado más allá del auto-deploy de Render on push a main.
- Autoscaling / tuning de recursos más allá de los defaults del free tier.
- VPC / red privada (no hay requisito de aislamiento de red).

## Criterios de aceptación

- [x] `docker-compose up` levanta `db` + `app`, y `curl
      localhost:8080/v1/responses` responde correctamente (mismo criterio
      que spec 05, pero corriendo dentro de Docker).
- [x] La imagen de `app` se construye sin errores (`docker build .`).
- [x] Verificado localmente end-to-end contra Supabase con una pregunta
      real (dispara `query_cv_tool`, retrieval correcto, sin cargar ningún
      modelo local — ver historial de cambios arriba).
- [ ] El servicio desplegado en Render responde igual que en local, con
      una pregunta real (no un input trivial) — pendiente de confirmar
      tras el redeploy con el código actualizado.

## Abierto / bloqueado

- **Free tier de Render duerme el servicio tras 15 min sin tráfico**
  (~30s de cold start al despertar). Aceptable para evaluación del reto.
- **Incidente resuelto**: el deploy en Render (free tier, 512MB RAM) causó
  un crash por OOM en cuanto una pregunta real invocaba `query_cv_tool`
  (cargaba `sentence-transformers`/torch, ~800MB-1GB). Se resolvió
  moviendo el embedding a la API de OpenRouter — ya no hay modelo pesado
  en el contenedor, no hace falta ni GCP ni un plan pago de Render. Ver
  `DEPLOY.md` para el detalle completo.
