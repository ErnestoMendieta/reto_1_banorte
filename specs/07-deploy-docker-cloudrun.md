# Spec 07 — docker-compose local + Dockerfile + deploy Cloud Run/Cloud SQL

## Objetivo

Contenedorizar la app para desarrollo local (2 contenedores: `db` + `app`)
y dejar el pipeline de deploy a producción documentado y ejecutable
(Cloud Run + Cloud SQL), según lo definido en PRD §4/§6.

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

### Deploy a producción (Cloud Run + Cloud SQL)

Pasos documentados (a ejecutar una vez exista el proyecto de GCP — ver
"Abierto / bloqueado"):

1. **Cloud SQL**: crear instancia de Postgres, habilitar la extensión
   `vector` (Cloud SQL soporta pgvector desde consola/flag), crear la DB y
   correr el schema de spec 01 + `scripts/ingest_cv.py` apuntando a esa
   instancia (vía Cloud SQL Auth Proxy desde local, una sola vez).
2. **Artifact Registry**: `gcloud builds submit --tag
   {region}-docker.pkg.dev/{project}/{repo}/cv-agent`.
3. **Secret Manager**: crear secretos `github-token`, `openrouter-api-key`,
   `database-url` (este último apuntando a Cloud SQL vía socket unix
   `/cloudsql/{instance_connection_name}`).
4. **Deploy**:
   ```
   gcloud run deploy cv-agent \
     --image {region}-docker.pkg.dev/{project}/{repo}/cv-agent \
     --add-cloudsql-instances {instance_connection_name} \
     --set-secrets=GITHUB_TOKEN=github-token:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,DATABASE_URL=database-url:latest \
     --region {region} \
     --allow-unauthenticated
   ```
   (`--allow-unauthenticated` porque el reto pide un endpoint accesible
   por un cliente compatible con Open Responses, sin auth multi-usuario —
   ver PRD, fuera de alcance la autenticación.)

## Fuera de alcance

- CI/CD automatizado (GitHub Actions, Cloud Build triggers) — deploy
  manual vía `gcloud` es suficiente para el reto.
- Autoscaling tuning más allá de los defaults de Cloud Run.
- VPC connector / red privada (no hay requisito de aislamiento de red para
  este alcance).

## Criterios de aceptación

- [ ] `docker-compose up` levanta `db` + `app`, y `curl
      localhost:8080/v1/responses` responde correctamente (mismo criterio
      que spec 05, pero corriendo dentro de Docker).
- [ ] La imagen de `app` se construye sin errores (`docker build .`).
- [ ] Los comandos `gcloud` de esta spec están documentados en un
      `DEPLOY.md` en la raíz del repo, listos para ejecutarse tal cual
      cuando exista el proyecto de GCP.
- [ ] (Bloqueado hasta tener proyecto GCP) El servicio desplegado en Cloud
      Run responde igual que en local — verificación real pendiente.

## Abierto / bloqueado

- **No hay proyecto de GCP creado todavía.** El código, `Dockerfile`,
  `docker-compose.yml` y los comandos de deploy se escriben y prueban
  igual (local funciona sin GCP); el paso 3-4 (deploy real) queda
  bloqueado hasta que el usuario cree el proyecto y habilite billing.
  Esto no bloquea cerrar el resto de esta spec.
