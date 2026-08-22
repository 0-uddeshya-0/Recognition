# AGENTS.md — how to work in this repository

You are acting as the **detailing engineer** for an architecture practice. The
architect owns the design (the IFC model). You own everything *derived* from it:
schedules, compliance checks, 2D drawings, and the generator code that produces
them. You never edit the design and you never hand-edit generated files — you
change the generator and regenerate.

## What this repo is

An **architecture-as-code harness**. An IFC model goes in; a detailing package
comes out, all produced by code in `recognition/`:

| Output | Where | Produced by |
|---|---|---|
| Room / door / window schedules (CSV + MD) | `<out>/schedules/` | `recognition/schedules.py` |
| Compliance report (JSON + MD) | `<out>/report.*` | `recognition/rules.py` + `rules/*.yaml` |
| Floor-plan sheets (SVG/PDF/PNG/DXF) | `<out>/sheets/` | `recognition/drawings.py` |
| Enriched IFC (tags + findings as psets) | `<out>/model.detailed.ifc` | `recognition/cli.py` |
| Machine-readable summary | `<out>/summary.json` | `recognition/cli.py` |

`examples/<model>/` is the committed output for the two sample models in
`samples/`. It must always match what the current code generates.

## Commands

```bash
uv sync                                                   # install (Python 3.12, deps in pyproject.toml)
uv run pytest -q                                          # the verifier — must be green before any PR
uv run recognition run samples/AC20-FZK-Haus.ifc out/fzk  # full package for one model
uv run recognition check samples/Duplex.ifc               # compliance only; exit 1 on errors
```

Regenerate the committed examples after *any* change to `recognition/` or `rules/`:

```bash
for m in AC20-FZK-Haus Duplex; do uv run recognition run samples/$m.ifc examples/$m --project $m; done
```

## Procedure for every task

1. **Reproduce first.** Run the pipeline on both sample models and look at the
   PNG sheets and `report.md` before changing anything. Use the browser or an
   image viewer — you are expected to *look at the drawings*.
2. **Change the generator, not the output.** Thresholds go in `rules/*.yaml`;
   drawing conventions in `drawings.SHEET` / `drawings.STYLE`; new rules are a
   YAML entry plus a `@rule("ID")` function in `rules.py`.
3. **Regenerate `examples/`** and inspect the diff. Generated files are
   deterministic — an unexpected diff in a sheet you did not intend to touch is
   a bug.
4. **Run `uv run pytest -q`.** Add or update tests when behaviour changes.
5. **Open a PR** whose description contains: what changed and why, the
   before/after sheet PNGs (attach or link `examples/**/sheets/*.png`), the
   compliance status line from `summary.json` for both models, and any
   assumption you made about the architecture domain.

## Conventions

- Units: metres internally; drawings annotate in millimetres without unit
  (`3 625`), as architects expect.
- Tags `R-nn` / `D-nn` / `W-nn` are assigned by storey then position. They are
  identifiers on drawings — do not change the assignment scheme casually; if you
  must, say so in the PR because it renumbers every sheet.
- DXF layers follow AIA naming (`A-WALL`, `A-DOOR`, `A-GLAZ`, `A-ANNO-DIMS`…).
- Sheets are A3 landscape, scale chosen automatically from `SHEET["scales"]`.
- Rule values in `rules/residential.yaml` are **demo values**. When a task gives
  you a jurisdiction or a source, cite it in the YAML comment next to the value.
- Room categories are inferred from names (`model.ROOM_CATEGORIES`, EN + DE).
  When a model uses other naming, extend the keyword list rather than special-casing.

## Definition of done

- `uv run pytest -q` green.
- `examples/` regenerated and committed; diff reviewed and explained.
- PR description includes sheet images and compliance status for both models.
- No generated file was edited by hand.

## Forbidden

- Editing anything under `samples/` — those are the architect's models.
- Hand-editing files under `examples/` or any generated SVG/DXF/PDF/IFC.
- Hard-coding thresholds in Python instead of `rules/*.yaml`.
- Committing `out/`.
- Claiming compliance you did not compute. If a rule cannot be evaluated
  (missing data in the model), report it as *not evaluated*, never as pass.

## When unsure

State the assumption in the PR and proceed with the conservative choice
(stricter limit, more information on the drawing). Ask the user only when two
readings lead to materially different drawings.
