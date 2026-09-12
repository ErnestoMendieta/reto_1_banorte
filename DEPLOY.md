# Deploy — Render + Supabase

Reemplaza los marcadores `{...}` con tus valores reales.

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
   No pongas `LOG_FORMAT` (deja el default `json`, así los logs de Render
   quedan parseables). No pongas `PORT` — Render lo inyecta solo y el
   `Dockerfile` ya lo respeta (`${PORT:-8080}`).
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

---

## Dev local (sin Render/Supabase)

```bash
docker-compose up --build
curl -X POST http://localhost:8080/v1/responses \
  -H "Content-Type: application/json" \
  -d '{"input": "¿Cuál es la experiencia laboral de Ernesto?"}'
```
