# Deploy — Render + Supabase (free tier, sin billing)

GCP se descartó: Cloud SQL (Postgres) no cae en su free tier y pide
billing habilitado. Render (app) + Supabase (Postgres/pgvector) son
gratis de forma permanente y se conectan directo al repo de GitHub
(`ErnestoMendieta/reto_1_banorte`). Cero cambios al `Dockerfile`.

## 1. Supabase — base de datos (Postgres + pgvector)

1. Crear proyecto en https://supabase.com (free tier).
2. SQL editor → `create extension if not exists vector;`.
3. Copiar el connection string del proyecto y correr la ingesta una sola
   vez desde local:
   ```bash
   DATABASE_URL="postgresql://<user>:<password>@<host>:5432/postgres" \
     python scripts/ingest_cv.py
   ```

## 2. Render — deploy de la app

1. https://render.com → "New Web Service" → conectar el repo de GitHub.
2. Environment: **Docker** (usa el `Dockerfile` del repo tal cual).
3. Agregar variables de entorno (Render → Environment, como secrets):
   `GITHUB_TOKEN`, `GITHUB_USERNAMES`, `OPENROUTER_API_KEY`,
   `OPENROUTER_MODEL`, `CV_TEX_PATH`, `LOG_FORMAT`, `DATABASE_URL`
   (la de Supabase del paso 1).
4. Deploy automático en cada push a `main`. Render detecta el puerto
   expuesto (`8080`) del Dockerfile.

## 3. Probar el endpoint desplegado

```bash
curl -X POST https://<tu-servicio>.onrender.com/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```

> Nota: el free tier de Render duerme el servicio tras 15 min sin
> tráfico (~30s de cold start al despertar). Si necesitas siempre-caliente:
> plan pago de Render, o Oracle Cloud Free Tier (VM Always Free) corriendo
> `docker-compose.yml` tal cual — ver spec 07.

---

## Dev local (sin GCP)

```bash
# Levantar DB + app en Docker
docker-compose up --build

# Probar el endpoint
curl -X POST http://localhost:8080/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```
