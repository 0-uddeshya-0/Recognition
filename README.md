# Recognition

**Architecture-as-code: an IFC model goes in, a detailing package comes out — and Devin maintains the code that makes it.**

Architects spend most of their hours not on design but on *detailing*: schedules, compliance checks, dimensioned drawings, and redoing all of it every time the design changes. Recognition turns that work into a derivation from the model, so a design change becomes "regenerate and review the diff" instead of a week of redrawing. The derivation is ordinary Python in a git repo, which means an AI software engineer can own it.

![FZK-Haus ground floor sheet](examples/AC20-FZK-Haus/sheets/A-101_Erdgeschoss.png)

*Generated from `samples/AC20-FZK-Haus.ifc` by `recognition run` — no hand edits.*

## The thesis

Any domain becomes a software project — with version history, branches, review, tests, and an AI engineer — once it has three things:

1. a **text source of truth** (here: the generator code + rule YAML; the IFC is the input),
2. a **verifier** (compliance rules + tests → pass/fail),
3. a **renderer** (sheets a human can judge).

This repo is the harness for architecture. The same shape applies to anything with an API.

## What it produces

```
model.ifc ──► recognition run ──►  schedules/   rooms.csv · doors.csv · windows.csv · schedules.md
                                   report.md / report.json   compliance: PASS | WARN | FAIL, per-element results
                                   sheets/      A-101_<storey>.svg · .pdf · .png · .dxf   (dimensioned plans)
                                   model.detailed.ifc         3D model with tags + findings as a property set
                                   summary.json               machine-readable summary (for UIs / Devin structured output)
```

Sheets carry: walls, room tags with areas, door swings, window symbols, exterior dimension chains (mm), north arrow, scale bar and a title block with sheet number, scale, date and git revision. DXF uses AIA layer names and opens in AutoCAD / Revit / ArchiCAD.

Committed output for both sample models lives in [`examples/`](examples/). The Duplex model fails compliance on purpose — six of its doors are 0.762 m wide:

> **Status: FAIL** — 71 checks, 64 passed, 7 errors, 0 warnings · `DOOR-MIN-WIDTH` D-03: leaf width 0.762 m < 0.8 m (interior) …

## Quick start

```bash
uv sync
uv run pytest -q                                                   # 10 tests on the sample models
uv run recognition run samples/AC20-FZK-Haus.ifc out/fzk --project FZK
uv run recognition check samples/Duplex.ifc                        # exit 1 → the verifier
```

Pure Python: `ifcopenshell` (IFC2x3 + IFC4), `shapely`, `svgwrite`, `cairosvg`, `ezdxf`. No CAD application required.

## Repository map

| Path | Role |
|---|---|
| `recognition/model.py` | IFC → walls, spaces, doors, windows with 2D footprints; deterministic tags; external-wall inference |
| `recognition/schedules.py` | Room / door / window schedules |
| `recognition/rules.py`, `rules/residential.yaml` | Compliance engine; thresholds are data, logic is code |
| `recognition/drawings.py` | Sheets: SVG/PDF/PNG + DXF sharing one symbol geometry |
| `recognition/cli.py` | `run` (full package) and `check` (gate) |
| `samples/` | Public sample IFC models (input — never edited) |
| `examples/` | Generated output for the samples (always regenerated, never hand-edited) |
| `tests/` | The verifier |
| `AGENTS.md`, `REVIEW.md`, `playbooks/`, `.devin/blueprint.yaml` | **The domain-expert layer for Devin** — see below |

## How Devin governs this repo

Devin is the detailing engineer; the architect never opens the Python.

- **`AGENTS.md`** — the procedure (reproduce → change the generator → regenerate → test → PR with images), conventions, definition of done, forbidden actions.
- **`playbooks/detailing.devin.md`** (`!detail`) — "here is a model, produce/refresh its package"; **`playbooks/rule-change.devin.md`** (`!rule`) — add or change a compliance rule.
- **`REVIEW.md`** — what Devin Review checks: generated files match the generator, no silent compliance regressions, tag stability, dimension sanity.
- **`.devin/blueprint.yaml`** — the environment (uv + deps), so every session boots ready to run.
- **`summary.json`** — the shape a UI or a Devin `structured_output_schema` consumes.

A typical request: *"Add a section through the stair on sheet A-201"* or *"Bedrooms must be ≥ 10 m² under the new code"* → Devin edits the generator or the YAML, regenerates, opens a PR with the new sheets attached and the compliance delta explained.

## Status and roadmap

Proof of concept built at a hackathon (August 2026). Working: loading, schedules, 6 rules, dimensioned plan sheets, DXF, enriched IFC, CLI, tests, Devin harness.

Next: sections (mesh slicing), wall-type assignment from an assembly library, a junction-detail library with callouts, a one-page UI that uploads an IFC and drives Devin through the API, and real jurisdiction rulesets.

**Disclaimer:** values in `rules/residential.yaml` are illustrative demo thresholds, not any jurisdiction's code.
