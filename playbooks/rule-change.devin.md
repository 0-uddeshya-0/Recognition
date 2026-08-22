# Playbook: add or change a compliance rule

Macro: `!rule`

## Procedure

1. `uv sync && uv run pytest -q` — green baseline.
2. Read `rules/residential.yaml` and `recognition/rules.py` to see how existing rules are declared (YAML) and implemented (`@rule("ID")` functions returning one `Result` per checked element, pass or fail).
3. For a **threshold change**: edit the value in YAML, add a comment with the source (code section, standard, or the user's instruction).
4. For a **new rule**: add the YAML entry (`id`, `title`, `severity`, `params`), implement the function in `rules.py` reading only `params`, and make sure it records passes as well as failures.
5. Add a test in `tests/test_pipeline.py` that asserts the rule's behaviour on a sample model (both a pass and a fail case if the samples allow it).
6. Regenerate `examples/` for both sample models; review the change in `report.md` and in `model.detailed.ifc` psets.
7. Open a PR titled `rules: <ID> — <one line>`.

## Specifications

- The rule appears in `report.md` with a checked count > 0 on at least one sample model.
- Tests pass; a new test covers the rule.
- PR description lists which elements changed status on each sample model and why.

## Advice and pointers

- Severity `error` fails `recognition check` (exit 1); `warning` does not. Use `error` only for hard code requirements.
- If a rule needs data the model may lack (e.g. fire rating), return no `Result` for that element and note "not evaluated" in the message of a single informational result, rather than inventing a pass.
- Geometry helpers: `Model.spaces_touching(el)` maps doors/windows to rooms; `model._rect_dims(geom)` gives (short, long) side of the minimum rotated rectangle.

## Forbidden actions

- Hard-coding thresholds in Python.
- Removing an existing rule without the user asking for it.

## Required from user

- The rule text or threshold, and its source if known.
