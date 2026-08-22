---
name: verify-repair
description: Run Recognition's deterministic verifier, read a verdict, and repair a failing design at the lowest layer that can satisfy the change.
---

# Verify, then repair at the lowest layer

The verifier is the only gate in this repository. Your work is finished when
it is green — never when you believe it is.

## Commands

```bash
uv sync                                            # once per machine
uv run pytest -q                                   # the regression half of the gate
uv run recognition autopilot briefs/<name>.json    # full loop, local engine, ~20 s
uv run recognition run <model.ifc> out/pkg         # detailing package for one IFC
uv run recognition check <model.ifc>               # compliance only; exit 1 on errors
```

Read `out/autopilot/<project>/<strategy>/verdict.json` — every finding carries
`tier`, `status`, `message`, and a citation. Only `tier: law` failures (and
triggered `standard`) block; `guidance` and `house` never do. Rules that report
`not_evaluated` are declared blind spots — they are **never** passes, and you
must not "fix" them by hiding them.

## Route a change to the lowest layer that can satisfy it

| The change is… | Re-enter at | Edit |
|---|---|---|
| A threshold or a new rule | L0 | `rules/by/*.yaml` — **only with a human-supplied citation** |
| The room programme / adjacency | L2 | the ArchitectPlan (plan.json input) |
| Local geometry ("move that wall") | L3 | `recognition/translate.py` |
| Drawing convention | L4 | `recognition/drawings.py` (`SHEET` / `STYLE`) |
| A wrong predicate | L5 | `recognition/rules.py` + a test |

## If your workspace runs the Fusion harness

Delegate the **mechanical** loop to the sidekick: `uv sync`, running pytest,
re-running the autopilot after each candidate fix, tailing verdict diffs,
regenerating `examples/`. Keep in the main agent the parts where judgement is
the deliverable: which layer to re-enter, what the failing finding actually
means, and the final review of the diff. That split is what the harness is
for — spend the frontier tokens only where they change the outcome.

## Forbidden

- Hand-editing anything generated: `examples/`, `out/`, `web/data/`, any
  SVG/DXF/PDF/IFC, or a `design.py` produced by the translator.
- Authoring or editing a rule threshold or citation without one supplied by a
  human — no LLM may originate regulation content.
- Claiming compliance you did not compute, or counting `not_evaluated` as pass.
- `git add -A` — stage files by name.

## Definition of done

- `uv run pytest -q` green, and the specific failing finding you were sent is
  now passing **for the reason the fix implies** (read the new verdict line).
- `examples/` regenerated and committed when `recognition/` or `rules/` changed.
- PR description: what changed, why, before/after sheet PNGs, the coverage
  line (`N checked · M not evaluated · K failed`), and any assumption made.
