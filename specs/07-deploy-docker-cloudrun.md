# Spec 07 — docker-compose local + Dockerfile + deploy Render/Supabase

## Objetivo

Contenedorizar la app para desarrollo local (2 contenedores: `db` + `app`)
y dejar el pipeline de deploy a producción documentado y ejecutable, según
lo definido en PRD §4/§6.

**Cambio de plataforma (2026-09-12):** se reemplaza Cloud Run + Cloud SQL
por **Render (app) + Supabase (Postgres/pgvector)** — ambos con free tier
permanente, sin requerir billing habilitado ni tarjeta para el proyecto de
GCP. Cero cambios al `Dockerfile`; solo cambia el destino del deploy y el
`DATABASE_URL`. Ver "Abierto / bloqueado" por el trade-off (cold start).

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

Ambos con free tier permanente (sin tarjeta / billing requerido). Repo ya
en GitHub (`ErnestoMendieta/reto_1_banorte`), deploy conectado directo
desde ahí.

1. **Supabase** (Postgres + pgvector):
   - Crear proyecto en supabase.com (free tier).
   - En el SQL editor: `create extension if not exists vector;`.
   - Copiar el connection string (modo "Session pooler" o directo) y
     correr una sola vez desde local: `DATABASE_URL=<supabase_url>
     python scripts/ingest_cv.py`.
2. **Render** (app, Web Service):
   - "New Web Service" → conectar el repo de GitHub → Environment:
     Docker (usa el `Dockerfile` tal cual, sin cambios).
   - Variables de entorno (Render → Environment, como secrets):
     `GITHUB_TOKEN`, `GITHUB_USERNAMES`, `OPENROUTER_API_KEY`,
     `OPENROUTER_MODEL`, `CV_TEX_PATH`, `LOG_FORMAT`, y `DATABASE_URL`
     apuntando a Supabase.
   - Puerto: Render detecta `EXPOSE 8080` del Dockerfile automáticamente.
3. **Verificar**: `curl -X POST https://<servicio>.onrender.com/v1/responses
   -H "Content-Type: application/json" -d '{"input": "..."}'`.

## Fuera de alcance

- CI/CD automatizado más allá del auto-deploy de Render on push a main.
- Autoscaling / tuning de recursos más allá de los defaults del free tier.
- VPC / red privada (no hay requisito de aislamiento de red).

## Criterios de aceptación

- [ ] `docker-compose up` levanta `db` + `app`, y `curl
      localhost:8080/v1/responses` responde correctamente (mismo criterio
      que spec 05, pero corriendo dentro de Docker).
- [ ] La imagen de `app` se construye sin errores (`docker build .`).
- [ ] El servicio desplegado en Render responde igual que en local contra
      la DB de Supabase.

## Abierto / bloqueado

- **Free tier de Render duerme el servicio tras 15 min sin tráfico**
  (~30s de cold start al despertar). Aceptable para evaluación del reto;
  si se necesita siempre-caliente, subir a un plan pago de Render o mover
  a una VM Always Free de Oracle Cloud corriendo `docker-compose.yml` tal
  cual (alternativa evaluada, descartada solo por mayor fricción de alta
  de cuenta).
- GCP se descartó como destino: Cloud SQL (Postgres) no cae en su free
  tier y requiere billing habilitado.
