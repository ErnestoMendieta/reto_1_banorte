# Deploy — Cloud Run + Supabase

Reemplaza los marcadores `{...}` con tus valores reales.

> **Por qué Cloud Run y no Render**: el free tier de Render da 512MB de RAM,
> insuficiente para cargar `sentence-transformers`/torch en `query_cv` — el
> proceso moría por OOM a media petición (502) en cuanto una pregunta real
> disparaba el tool call. Cloud Run permite subir la memoria del contenedor
> (`--memory 1Gi`) sin costo si el tráfico se mantiene dentro del free tier
> (2M requests/mes) — Cloud SQL era lo único que cobraba antes, y ya no se
> usa (la DB vive en Supabase).

---

## 1. Supabase — base de datos

1. Crea un proyecto en [supabase.com](https://supabase.com).
2. En **Project Settings → Database → Connection string**, copia la cadena en
   modo **Session** (puerto `5432`, no el pooler de `6543` — `psycopg2` usa
   conexiones persistentes normales, no serverless). Se ve así:
   ```
   postgresql://postgres:{tu-password}@db.{project-ref}.supabase.co:5432/postgres
   ```
3. Habilita la extensión `vector` desde **Database → Extensions** en el
   dashboard de Supabase (búscala como `vector` y actívala). Si tu rol ya
   tiene permiso, `scripts/ingest_cv.py` también intenta
   `CREATE EXTENSION IF NOT EXISTS vector` solo — pero confírmalo primero en
   el dashboard si la ingesta falla con un error de permisos.
4. Corre la ingesta desde tu máquina apuntando a Supabase:
   ```bash
   DATABASE_URL="postgresql://postgres:{tu-password}@db.{project-ref}.supabase.co:5432/postgres" \
     python scripts/ingest_cv.py
   ```
   Esto crea `cv_documents`/`cv_embeddings` y carga el CV. Vuelve a correrlo
   (sin `--reembed`) si cambias `data/cv.tex`; es idempotente (usa
   `TRUNCATE CASCADE`).

## 2. Cloud Run — servicio de la app

Requiere `gcloud` CLI instalado (`gcloud init` para loguearte) y un
proyecto de GCP con billing habilitado (necesario para activar la API de
Cloud Run, aunque no se cobre mientras el uso quede dentro del free tier).

```bash
gcloud config set project {tu-proyecto-gcp}
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

- `--source .`: Cloud Build construye la imagen desde tu `Dockerfile` tal
  cual (no hace falta Artifact Registry manual ni `gcloud builds submit`
  aparte, este comando hace build + deploy en un paso).
- `--memory 1Gi`: el default de Cloud Run es 512MB, **la misma memoria que
  hizo crashear el servicio en Render** — no la bajes.
- No pongas `PORT`: Cloud Run lo inyecta solo (`8080` por default) y el
  `Dockerfile` ya lo respeta.
- El comando imprime la URL del servicio (`https://cv-agent-xxxx.run.app`)
  al terminar.

Prueba:
```bash
curl -X POST https://{tu-servicio}.run.app/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```

## Cosas a saber antes de confiar en esto para tráfico real

- **Cloud Run escala a cero sin tráfico** (comportamiento default, igual
  que Render) — la primera request tras un rato inactivo tarda más (cold
  start) mientras arranca un contenedor nuevo. Para evitarlo: `--min-instances 1`
  (deja de ser gratis, cobra por el tiempo que el contenedor está de pie).
- **Las conversaciones viven en memoria** (`_conversations` en
  `scripts/api.py`) — cada vez que el contenedor escala a cero o se
  reinicia, se pierden todas. No hay persistencia de conversación entre
  reinicios (sería trabajo aparte, no está en el alcance actual).
- **Rate limit de OpenRouter para cuentas nuevas** (20 req/min en
  `gemini-3.6-flash`): el agente ya reintenta automáticamente ante un 429
  (`scripts/retry.py`, hasta ~21s de espera adicional por mensaje), pero con
  tráfico real de varios usuarios a la vez la cuota se agota igual — el
  retry amortigua, no elimina el límite. Sube de tier en OpenRouter cuando
  el tráfico lo justifique.

---

## Dev local (sin Cloud Run/Supabase)

```bash
docker-compose up --build
curl -X POST http://localhost:8080/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```
