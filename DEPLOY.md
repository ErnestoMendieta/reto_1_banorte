# Deploy — Cloud Run + Cloud SQL

Comandos listos para ejecutarse cuando exista el proyecto de GCP y esté
habilitado el billing. Reemplaza los marcadores `{...}` con tus valores reales.

| Marcador | Ejemplo |
|---|---|
| `{project}` | `banorte-cv-agent` |
| `{region}` | `us-central1` |
| `{repo}` | `cv-agent` (Artifact Registry repo name) |
| `{instance_connection_name}` | `banorte-cv-agent:us-central1:cvagent-db` |

---

## 1. Cloud SQL — base de datos

```bash
# Crear instancia Postgres 16 con pgvector
gcloud sql instances create cvagent-db \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region={region} \
  --database-flags=cloudsql.enable_pgvector=on

# Crear la base de datos y el usuario
gcloud sql databases create cvagent --instance=cvagent-db
gcloud sql users create cvagent --instance=cvagent-db --password=CHANGE_ME

# Una vez creada: correr el schema + ingesta desde local vía Cloud SQL Auth Proxy
cloud-sql-proxy {instance_connection_name} &
DATABASE_URL="postgresql://cvagent:CHANGE_ME@127.0.0.1:5432/cvagent" \
  python scripts/ingest_cv.py
```

## 2. Artifact Registry — imagen Docker

```bash
# Crear repositorio (una sola vez)
gcloud artifacts repositories create {repo} \
  --repository-format=docker \
  --location={region}

# Autenticar Docker con Artifact Registry
gcloud auth configure-docker {region}-docker.pkg.dev

# Construir y subir la imagen
gcloud builds submit --tag {region}-docker.pkg.dev/{project}/{repo}/cv-agent
```

## 3. Secret Manager — variables sensibles

```bash
# Crear los secretos (rellenar con los valores reales)
echo -n "GITHUB_TOKEN_VALUE" | \
  gcloud secrets create github-token --data-file=-

echo -n "OPENROUTER_API_KEY_VALUE" | \
  gcloud secrets create openrouter-api-key --data-file=-

# DATABASE_URL apunta a Cloud SQL vía socket Unix
echo -n "postgresql+psycopg2://cvagent:CHANGE_ME@/cvagent?host=/cloudsql/{instance_connection_name}" | \
  gcloud secrets create database-url --data-file=-
```

## 4. Deploy a Cloud Run

```bash
gcloud run deploy cv-agent \
  --image {region}-docker.pkg.dev/{project}/{repo}/cv-agent \
  --add-cloudsql-instances {instance_connection_name} \
  --set-secrets=GITHUB_TOKEN=github-token:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,DATABASE_URL=database-url:latest \
  --region {region} \
  --allow-unauthenticated
```

> `--allow-unauthenticated`: el reto pide un endpoint accesible por cualquier
> cliente compatible con Open Responses sin auth multi-usuario (ver PRD §7).

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
