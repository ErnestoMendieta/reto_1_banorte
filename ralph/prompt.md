# Ralph Loop — Agente conversacional de CV (Reto Banorte)

Eres un agente autónomo. Implementa **una sola** user story por iteración del
proyecto "Agente conversacional de CV".

## Orden obligatorio de cada iteración

1. **Lee primero** `ralph/progress.txt`, en especial la sección "Codebase
   Patterns". No repitas trabajo ni descubrimientos ya anotados.
2. **Lee** `ralph/AGENT.md` (convenciones y comandos de validación) y
   `reto-banorte-cv-agent-PRD.md` (contexto de producto).
3. **Lee** `ralph/prd.json` y elige la user story de menor `priority` que
   tenga `"passes": false`. Implementa **solo esa**.
4. **Lee la spec exacta** de esa story en `specs/0N-*.md` (el mapeo
   story→spec está en la descripción de cada story dentro de `prd.json`, y
   en la tabla de `specs/README.md`). El contrato ahí (schemas, nombres de
   función, shapes de request/response) es la fuente de verdad, no lo
   reinterpretes.
5. **Busca en el código antes de crear nada.** Usa Grep/Glob/Read para
   confirmar qué existe ya. Nunca asumas que un archivo o patrón no existe
   sin verificarlo.
6. **Implementa la story** respetando las convenciones de `ralph/AGENT.md`:
   - Una story por iteración, cambios mínimos y enfocados.
   - No inventes datos del candidato ni información fuera de lo que las
     tools devuelvan.
   - Nunca commitees `.env`.
7. **Valida** con los comandos exactos de `ralph/AGENT.md` según lo que
   tocaste (`ruff check .` + `pytest`, o los comandos de Docker si aplica).
   Si la validación falla, **arregla** antes de continuar. No commitees roto.
8. **Actualiza el estado:**
   - En `ralph/prd.json`: marca la story con `"passes": true` y escribe en
     `notes` un resumen breve de lo implementado (incluye cualquier bloqueo
     real, p.ej. GCP no provisionado en US-007).
   - En `specs/README.md`: actualiza la fila de esa spec a `hecho`.
   - Haz **append** (no sobrescribir) a `ralph/progress.txt` en la sección
     "Iteration Log": id de la story, qué se hizo, archivos tocados,
     resultado de la validación, y cualquier patrón nuevo en
     "Codebase Patterns".
9. **Commit** atómico de la story:
   ```
   feat: [US-XXX] - <título exacto de la story>
   ```

## Reglas

- **Una story por iteración.** Si la story elegida ya está completa y
  validada, termina; no empieces otra.
- Si todas las stories tienen `"passes": true`, no hagas cambios: reporta que
  el proyecto está completo y **termina**.
- Respeta el orden de `priority` — las stories tienen dependencias reales
  entre sí (ver `specs/README.md`).
- Cambios mínimos y enfocados; nada fuera del alcance de la story actual.
