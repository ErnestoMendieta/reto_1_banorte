# Spec 01 — Schema de Postgres + ingesta del CV

## Objetivo

Tener una base de datos Postgres con pgvector poblada con los chunks del
CV y sus embeddings, lista para que la spec 02 (`query_cv`) haga retrieval
semántico sobre ella.

## Dependencias

- Ninguna (es el punto de partida del build).
- Requiere el `.tex` fuente del CV disponible en el repo (formato Harvard,
  2 páginas) — colocarlo en `data/cv/cv.tex` (o ruta equivalente,
  documentar la elegida en `CV_TEX_PATH`).

## Contrato concreto

### Variables de entorno

```
DATABASE_URL=postgresql://user:pass@db:5432/cvagent
CV_TEX_PATH=./data/cv/cv.tex
EMBEDDING_MODEL=<checkpoint Qwen local, 2-3B, a confirmar en implementación>
EMBEDDING_DIM=<dimensión de salida del modelo elegido>
```

`EMBEDDING_DIM` debe ser parametrizable — no hardcodear la dimensión en el
schema SQL, generarlo en migración a partir de esta env var.

### Schema SQL — dos tablas (contenido separado de embeddings)

Se separa el contenido del chunk (`cv_documents`) de su representación
vectorial (`cv_embeddings`), en vez de una sola tabla combinada. Razón:
el checkpoint exacto de `EMBEDDING_MODEL` (Qwen local 2-3B) todavía no
está fijado (ver "Abierto / bloqueado") — con dos tablas, cambiar o
comparar modelos de embedding es regenerar solo `cv_embeddings`, sin
re-parsear ni duplicar el contenido del CV. También permite tener más de
un modelo coexistiendo (útil para comparar antes de decidir el default).

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE cv_documents (
    id           SERIAL PRIMARY KEY,
    section      TEXT NOT NULL,        -- p.ej. "Experiencia", "Educación", "Skills"
    entry_title  TEXT,                 -- p.ej. nombre del puesto/proyecto; NULL si la sección no se sub-divide
    content      TEXT NOT NULL,        -- texto plano del chunk
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cv_embeddings (
    id           SERIAL PRIMARY KEY,
    document_id  INTEGER NOT NULL REFERENCES cv_documents(id) ON DELETE CASCADE,
    model_name   TEXT NOT NULL,        -- checkpoint exacto usado, p.ej. "qwen2.5-embed-3b"
    embedding    VECTOR(EMBEDDING_DIM) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, model_name)   -- un embedding por (chunk, modelo)
);

CREATE INDEX cv_embeddings_embedding_idx
    ON cv_embeddings USING hnsw (embedding vector_cosine_ops);
```

`model_name` en `cv_embeddings` es lo que garantiza que el retrieval (spec
02) nunca compare embeddings de modelos distintos: la query de similitud
siempre filtra `WHERE model_name = :embedding_model` con el mismo
`EMBEDDING_MODEL` configurado en el server.

### Estrategia de chunking (ver PRD §7)

1. Parsear `cv.tex` directamente (no el PDF renderizado) buscando los
   bloques de `\section{...}` (o el macro equivalente de la clase LaTeX
   usada — inspeccionar el archivo real antes de fijar el parser, puede
   ser `\section`, `\cvsection`, u otro según la plantilla).
2. Cada sección de nivel top (Educación, Skills, etc.) → 1 chunk, salvo:
3. **Experiencia** y **Proyectos**: sub-dividir por entrada individual
   (cada trabajo / cada proyecto es su propio chunk), porque es la
   granularidad en la que un reclutador pregunta.
4. `metadata` guarda al menos: `{"raw_length": <int>, "source": "cv.tex"}`.

### Script de ingesta

Ubicación sugerida: `scripts/ingest_cv.py`.

- Idempotente: al re-ejecutarse, hace `TRUNCATE cv_documents CASCADE`
  (el `CASCADE` borra también las filas de `cv_embeddings` por la FK)
  antes de insertar — no debe duplicar filas en cada corrida.
- Pasos:
  1. Parsear `.tex` → generar lista de chunks (section, entry_title, content).
  2. Insertar cada chunk en `cv_documents`, obtener su `id`.
  3. Generar embedding de cada chunk con `EMBEDDING_MODEL`.
  4. Insertar en `cv_embeddings` con `document_id`, `model_name =
     EMBEDDING_MODEL`, y el vector.
- Re-embeber con un modelo nuevo sin re-parsear: si `cv_documents` ya está
  poblada, el script debe soportar un modo que solo regenere
  `cv_embeddings` para un `model_name` distinto (upsert por `(document_id,
  model_name)`), sin tocar `cv_documents`.
- Debe poder correrse como comando suelto: `python scripts/ingest_cv.py`
  (usado tanto en desarrollo local como en un paso de inicialización del
  contenedor `app`, ver spec 07).

## Fuera de alcance

- Ingesta incremental/watch de cambios en el `.tex` (se re-corre el script
  manualmente cuando el CV cambia).
- Extracción desde el PDF renderizado (explícitamente descartada, ver PRD §7).

## Criterios de aceptación

- [ ] `python scripts/ingest_cv.py` corre sin error contra un Postgres con
      la extensión `vector` habilitada y deja `cv_documents` y
      `cv_embeddings` pobladas (mismo número de filas en ambas para el
      `model_name` configurado).
- [ ] El número de filas resultantes es coherente con las secciones +
      entradas individuales del CV real (verificar a mano contra el `.tex`).
- [ ] Volver a correr el script no duplica filas (idempotencia) en
      ninguna de las dos tablas.
- [ ] Una query manual con join (`SELECT d.content FROM cv_embeddings e
      JOIN cv_documents d ON d.id = e.document_id WHERE e.model_name =
      '<EMBEDDING_MODEL>' ORDER BY e.embedding <=> '<embedding de una
      pregunta de prueba>' LIMIT 3`) devuelve el chunk correcto para al
      menos 3 preguntas de prueba conocidas (p.ej. "¿dónde trabajaste
      antes?", "¿qué stack usaste en X proyecto?").
- [ ] Correr la ingesta con un segundo `model_name` distinto no borra ni
      duplica los embeddings del primero — ambos coexisten en
      `cv_embeddings`.

## Abierto / bloqueado

- Checkpoint exacto de `EMBEDDING_MODEL` (Qwen local 2-3B) por confirmar
  al implementar — cualquier checkpoint sirve mientras exponga embeddings
  de dimensión fija y corra local (sin llamada a API externa).
- Estructura exacta de macros del `.tex` fuente — ajustar el parser una
  vez el archivo esté en el repo.
