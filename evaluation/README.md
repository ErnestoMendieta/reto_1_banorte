# evaluation/ — Dataset de validación del agente de CV

Ground-truth para evaluar `scripts/orchestrator.py::run_agent`. Este dataset
**no incluye el runner de ejecución** (trabajo futuro) — solo las preguntas,
el comportamiento esperado, y los checks que un runner debe aplicar.

## Archivos

- `dataset.json` — 22 casos de prueba, ver schema abajo.

## Cómo un runner futuro debe consumir esto

1. Cargar `dataset.json["cases"]`.
2. Para cada caso, construir los `turns` como `HumanMessage` e invocarlos
   contra `run_agent` (import directo desde `scripts.orchestrator`, **no**
   vía HTTP — la API en `scripts/api.py` no expone los `ToolMessage`
   intermedios que este dataset necesita inspeccionar). Turnos múltiples se
   encadenan pasando el `state` devuelto por el turno anterior.
3. Verificar `expected_tool_calls` contra los `tool_calls` reales que
   aparecieron en los `AIMessage` de la corrida, según
   `expected_tool_calls_match` (`"all"`/`"any"`/`"none"`).
4. Aplicar `expected_keywords_any` / `expected_keywords_all` /
   `forbidden_keywords` (case-insensitive, normalizar acentos) sobre el
   texto del último `AIMessage`.
5. Para `check_type: "refusal"` y `"adversarial_guardrail"`, el matching por
   keywords es un apoyo débil — la evaluación real recomendada es humana o
   vía LLM-judge, usando el campo `expected_behavior` como rúbrica.
6. Casos con `repeat > 1` deben correrse esa cantidad de veces; todas las
   corridas deben pasar (no-determinismo del LLM, ver `specs/06-guardrails.md`
   y las acceptance criteria de US-006).
7. Casos con `runnable_live: false` no se pueden correr contra el agente real
   tal cual — requieren un modo de runner que mockee el resultado de una tool
   (ver `adv-003`). Documentar como "no ejecutado" en el reporte del runner,
   no como fallo.


## Categorías

| category      | qué valida                                                |
|---------------|------------------------------------------------------------|
| `cv_direct`   | retrieval correcto sobre el CV (`query_cv_tool`)            |
| `github`      | uso correcto de `query_github_tool` y sus 5 aspectos        |
| `multi_tool`  | el agente encadena `query_cv_tool` + `query_github_tool`    |
| `continuity`  | continuidad conversacional vía `state` (2 turnos)           |
| `out_of_scope`| rehúsa sin inventar (salario, edad, experiencia bancaria)   |
| `small_talk`  | no invoca tools para saludos                                |
| `adversarial` | guardrails anti-prompt-injection (US-006), correr x3        |

## Schema de cada caso

```
id                        str   — "<prefijo>-NNN", único
category                  enum  — cv_direct | github | multi_tool | continuity | out_of_scope | small_talk | adversarial
description               str   — etiqueta humana corta
turns                     list[{role: "user", content: str}]  — 1 turno, o 2+ para continuidad
expected_tool_calls       list[{name: "query_cv_tool"|"query_github_tool", args_hint: object}]  — puede ser []
expected_tool_calls_match enum  — "all" (deben ocurrir todas) | "any" (al menos una) | "none"
check_type                enum  — keyword_match | refusal | no_tool_call | graceful_degradation | adversarial_guardrail
expected_keywords_any     list[str] | null   — al menos una debe aparecer (case-insensitive)
expected_keywords_all     list[str] | null   — todas deben aparecer
forbidden_keywords        list[str] | null   — ninguna debe aparecer (fuga de prompt, alucinación)
expected_behavior         str   — SIEMPRE presente; rúbrica para revisión humana o LLM-judge futuro
repeat                    int   — veces a correr (3 para adversariales, por no-determinismo)
runnable_live             bool  — false solo en adv-003 (requiere mockear un tool_result)
source_grounding          str | null — sección exacta del CV/aspecto de GitHub de donde sale la verdad
notes                     str | null
```

Campos obligatorios en todo caso: `id, category, description, turns,
expected_tool_calls, expected_tool_calls_match, check_type,
expected_behavior, repeat, runnable_live`. El resto son opcionales (`null` si no aplica). El schema estático se valida en
`tests/test_evaluation_dataset.py` (sin ejecutar el agente, sin DB, sin red).
