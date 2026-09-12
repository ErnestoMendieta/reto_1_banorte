# Deploy — Render + Supabase

Reemplaza los marcadores `{...}` con tus valores reales.

> **Historial**: se intentó Render → GCP Cloud Run → **de vuelta a Render**.
> La causa real del 502 en Render no era falta de RAM en general, era que
> `query_cv` cargaba `sentence-transformers`/torch (~800MB-1GB) para calcular
> embeddings localmente — eso sí rebasaba el free tier de Render (512MB).
> La solución de raíz fue mover el cálculo de embeddings a la API de
> OpenRouter (`google/gemini-embedding-2`) — el contenedor ya no carga
> ningún modelo pesado, así que el free tier de Render (512MB) alcanza de
> sobra. No hace falta GCP ni pagar un plan superior de Render.

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
   Esto crea `cv_documents`/`cv_embeddings` (embeddings vía OpenRouter,
   `google/gemini-embedding-2`, 768 dims) y carga el CV. Vuelve a correrlo
   (sin `--reembed`) si cambias `data/cv.tex`; es idempotente (usa
   `TRUNCATE CASCADE`).
   > Si ya habías ingestado antes con el modelo local de
   > `sentence-transformers` (384 dims), borra la tabla vieja primero —
   > la dimensión cambió: `DROP TABLE IF EXISTS cv_embeddings CASCADE;`
   > (vía SQL Editor de Supabase o `psql`), luego corre la ingesta de nuevo.

## 2. Render — servicio web

1. En [render.com](https://render.com), **New → Web Service**, conecta el
   repo de GitHub.
2. **Runtime: Docker** (Render detecta el `Dockerfile` solo). No hace falta
   configurar build/start command.
3. **Environment variables** (Render → tu servicio → Environment):
   ```
   OPENROUTER_API_KEY=...
   OPENROUTER_MODEL=google/gemini-3.6-flash
   GITHUB_TOKEN=...
   GITHUB_USERNAMES=ErnestoMendieta,ErnestoMCUpiit
   DATABASE_URL=postgresql://postgres:{tu-password}@db.{project-ref}.supabase.co:5432/postgres
   ```
   No hace falta `EMBEDDING_MODEL`/`EMBEDDING_DIM` — los defaults del código
   (`google/gemini-embedding-2`, 768) ya coinciden con la ingesta. No pongas
   `LOG_FORMAT` (deja el default `json`). No pongas `PORT` — Render lo
   inyecta solo y el `Dockerfile` ya lo respeta (`${PORT:-8080}`).
4. Deploy. Prueba:
   ```bash
   curl -X POST https://{tu-servicio}.onrender.com/v1/responses \
     -H "Content-Type: application/json" \
     -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
   ```

## Cosas a saber antes de confiar en esto para tráfico real

- **Plan free de Render duerme el servicio tras ~15 min sin requests** y
  tarda ~30-50s en despertar en la siguiente request (cold start). El plan
  "Starter" en adelante no duerme. Mientras estés en free, el primer mensaje
  de cada conversación después de una pausa va a tardar ese cold start.
- **Las conversaciones viven en memoria** (`_conversations` en
  `scripts/api.py`) — cada vez que el servicio duerme/reinicia, se pierden
  todas. No hay persistencia de conversación entre reinicios, ni en free ni
  en planes pagos (sería trabajo aparte, no está en el alcance actual).
- **Rate limit de OpenRouter para cuentas nuevas** (20 req/min en
  `gemini-3.6-flash`): el agente ya reintenta automáticamente ante un 429
  (`scripts/retry.py`, hasta ~21s de espera adicional por mensaje), pero con
  tráfico real de varios usuarios a la vez la cuota se agota igual — el
  retry amortigua, no elimina el límite. Sube de tier en OpenRouter cuando
  el tráfico lo justifique.
- **Costo de embeddings por OpenRouter**: pago por token, pero para el
  volumen de este reto (ingesta única de ~12 chunks + preguntas puntuales)
  es de fracciones de centavo de dólar en total.

---

## Dev local (sin Render/Supabase)

```bash
docker-compose up --build
curl -X POST http://localhost:8080/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```
