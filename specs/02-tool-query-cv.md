# Spec 02 — Tool `query_cv`

## Objetivo

Exponer una tool invocable por el LLM orquestador (spec 04) que hace
retrieval semántico sobre `cv_documents`/`cv_embeddings` (spec 01) y
devuelve los fragmentos del CV relevantes a una pregunta.

## Dependencias

- Spec 01 (schema de dos tablas + datos poblados en `cv_documents` y
  `cv_embeddings`).

## Contrato concreto

### Schema de la tool (function calling)

```json
{
  "name": "query_cv",
  "description": "Busca información en el CV del candidato (experiencia, educación, skills, proyectos) relevante a una pregunta. Devuelve únicamente texto extraído del CV, nunca información inventada.",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {
        "type": "string",
        "description": "Pregunta o tema a buscar en el CV, en lenguaje natural."
      },
      "top_k": {
        "type": "integer",
        "description": "Número de fragmentos a devolver.",
        "default": 4
      }
    },
    "required": ["question"]
  }
}
```

### Función interna

```python
def query_cv(question: str, top_k: int = 4) -> list[ChunkResult]:
    ...

class ChunkResult(TypedDict):
    section: str
    entry_title: str | None
    content: str
    similarity: float  # 0-1, mayor = más similar
```

### Comportamiento

1. Generar embedding de `question` con el mismo `EMBEDDING_MODEL` usado en
   ingesta (spec 01).
2. Buscar los `top_k` chunks más cercanos por similitud coseno, con un
   **join entre las dos tablas filtrado por modelo** — esto es lo que
   garantiza que nunca se comparen embeddings de checkpoints distintos
   (en vez de una convención manual, es un `WHERE` explícito):
   ```sql
   SELECT d.section, d.entry_title, d.content,
          1 - (e.embedding <=> :query_embedding) AS similarity
   FROM cv_embeddings e
   JOIN cv_documents d ON d.id = e.document_id
   WHERE e.model_name = :embedding_model
   ORDER BY e.embedding <=> :query_embedding
   LIMIT :top_k;
   ```
3. Aplicar un **umbral mínimo de similitud** (configurable vía env var
   `CV_SIMILARITY_THRESHOLD`, default sugerido 0.3-0.4 — calibrar en
   pruebas): si ningún chunk lo supera, devolver lista vacía en vez de
   forzar resultados irrelevantes.
4. El texto de cada chunk se devuelve tal cual está en
   `cv_documents.content` — esta tool no resume ni reescribe, solo
   recupera.

### Wrapping al inyectar al LLM (ver spec 06)

Cuando el resultado de esta tool se agrega de vuelta al contexto del LLM,
debe envolverse como dato confiable pero no como instrucción (el CV es
contenido propio del candidato, pero igual se aplica el mismo patrón de
delimitación que a `query_github` por consistencia — ver spec 06).

## Fuera de alcance

- Re-ranking adicional sobre los resultados de similitud coseno (no se
  justifica con un CV de 2 páginas / pocos chunks).
- Cache de embeddings de preguntas repetidas (volumen demasiado bajo para
  que importe).

## Criterios de aceptación

- [ ] Preguntar por una experiencia laboral específica que existe en el CV
      devuelve el chunk correcto en el `top_k`.
- [ ] Preguntar algo que no está en el CV (p.ej. un dato inventado) devuelve
      lista vacía, no un chunk irrelevante forzado.
- [ ] `top_k` respeta el default (4) si no se especifica.
- [ ] La función es una unidad testeable de forma aislada (sin necesidad de
      levantar el orquestador completo) — debe tener al menos un test
      automatizado contra la base de datos de prueba.

## Abierto / bloqueado

Ninguno — depende solo de que spec 01 esté cerrada.
