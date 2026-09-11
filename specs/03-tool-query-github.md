# Spec 03 — Tool `query_github`

## Objetivo

Exponer una tool invocable por el LLM orquestador (spec 04) que consulta
la API de GitHub para responder preguntas sobre los repos del candidato
(qué hace un repo, qué stack usa, actividad reciente).

## Dependencias

- Ninguna spec previa — sí depende de `GITHUB_TOKEN` en `.env` (ya
  provisto) y de `GITHUB_USERNAME` (agregar a `.env` si no está).

## Contrato concreto

### Autenticación

REST API v3, `https://api.github.com`, header
`Authorization: Bearer ${GITHUB_TOKEN}`. Con token: 5,000 req/hora. Sin
token: 60 req/hora — usar siempre el token en todos los requests de esta
tool.

### Schema de la tool (function calling)

```json
{
  "name": "query_github",
  "description": "Consulta los repositorios públicos de GitHub del candidato: lista de repos, detalle de un repo, lenguajes usados, contenido del README, o actividad reciente (commits).",
  "parameters": {
    "type": "object",
    "properties": {
      "aspect": {
        "type": "string",
        "enum": ["list_repos", "repo_overview", "languages", "readme", "activity"],
        "description": "Qué aspecto consultar."
      },
      "repo_name": {
        "type": "string",
        "description": "Nombre del repo (sin owner). Requerido para todo aspecto excepto 'list_repos'."
      }
    },
    "required": ["aspect"]
  }
}
```

### Mapeo aspect → endpoint

| `aspect` | Endpoint |
|---|---|
| `list_repos` | `GET /users/{GITHUB_USERNAME}/repos` |
| `repo_overview` | `GET /repos/{GITHUB_USERNAME}/{repo_name}` |
| `languages` | `GET /repos/{GITHUB_USERNAME}/{repo_name}/languages` |
| `readme` | `GET /repos/{GITHUB_USERNAME}/{repo_name}/readme` (contenido en base64, decodificar) |
| `activity` | `GET /repos/{GITHUB_USERNAME}/{repo_name}/commits?per_page=5` |

### Función interna

```python
def query_github(aspect: str, repo_name: str | None = None) -> GithubResult:
    ...

class GithubResult(TypedDict):
    ok: bool
    data: dict | list | None   # payload relevante ya normalizado (no el JSON crudo de GitHub)
    error: str | None          # p.ej. "rate_limited", "repo_not_found"
```

### Manejo de rate limit y errores

- Leer headers `X-RateLimit-Remaining` / `X-RateLimit-Reset` en cada
  respuesta.
- Si `X-RateLimit-Remaining` llega a 0, o la respuesta es 403 por rate
  limit: devolver `{ok: False, error: "rate_limited"}` — la tool nunca
  debe lanzar una excepción sin controlar hacia el orquestador.
- Si el repo no existe (404): `{ok: False, error: "repo_not_found"}`.

### Contenido no confiable (ver spec 06)

El texto de `readme` y de `description`/`repo_overview` es contenido
externo (puede incluir texto escrito por terceros, colaboradores, forks).
Al inyectarse de vuelta al contexto del LLM, debe envolverse con el
delimitador de dato no confiable definido en spec 06 — este es el vector
de prompt-injection más realista del sistema.

## Fuera de alcance

- GraphQL API (REST v3 es suficiente para estos 5 aspectos).
- Repos privados / autenticación OAuth de terceros.
- Caché persistente de respuestas de GitHub (para el volumen de esta demo,
  no se justifica).

## Criterios de aceptación

- [ ] `aspect: "list_repos"` devuelve la lista de repos públicos del
      usuario configurado.
- [ ] `aspect: "readme"` con un `repo_name` válido devuelve el texto
      decodificado (no base64 crudo).
- [ ] Simular una respuesta 403 de rate-limit y verificar que la tool
      devuelve `{ok: False, error: "rate_limited"}` en vez de lanzar una
      excepción no controlada.
- [ ] `repo_name` inexistente devuelve `{ok: False, error:
      "repo_not_found"}`.

## Abierto / bloqueado

- **Alcance de repos a consultar**: por default, todos los públicos de
  `GITHUB_USERNAME` (vía `list_repos`). El usuario proveerá un `.txt` con
  links más adelante que puede acotar esto a una lista curada — cuando
  llegue, agregar filtro opcional `ALLOWED_REPOS` (env var, lista separada
  por comas) que, si está presente, restringe `list_repos` y valida
  `repo_name` contra esa lista. No bloquea implementar el resto de la tool
  ahora.
