# REVIEW.md — what a reviewer checks on a PR in this repo

This repository produces architectural deliverables from code. Review the PR the
way a senior detailer reviews a drawing set, not only the way an engineer
reviews Python.

## Always

- **Generated files match the generator.** If `recognition/` or `rules/` changed,
  `examples/` must be regenerated in the same PR. If `examples/` changed but no
  generator did, ask why.
- **No hand edits** to anything under `examples/`, or to `samples/*.ifc`.
- **Compliance status did not regress silently.** A model going from `PASS` to
  `FAIL`, or findings disappearing, needs an explanation in the PR description.
- **Thresholds live in YAML** (`rules/*.yaml`) with a source comment. Flag any
  numeric limit hard-coded in `rules.py`.
- **Tags are stable.** A diff that renumbers `R-`/`D-`/`W-` tags across a sheet
  must be called out in the PR title — it invalidates references on every other
  drawing.
- **Tests** cover behaviour changes; `uv run pytest -q` is green.

## Drawings (`recognition/drawings.py`, `examples/**/sheets/*`)

- Dimension chains: segment values sum to the overall dimension; no segments
  under 50 mm; stations only on exterior faces and exterior openings.
- Door swings open into a room, never into a wall; one arc per door.
- Every room has a tag, a name and an area; labels do not sit on walls.
- Title block: sheet number, scale, date, revision present; scale actually fits
  the sheet (nothing outside the border).
- DXF: layers follow the `A-*` naming; units are millimetres.

## Rules (`recognition/rules.py`, `rules/*.yaml`)

- Each rule records passes and failures (coverage visible in the report).
- Rules that cannot be evaluated do not report pass.
- Severity `error` is reserved for hard requirements.

## Model loading (`recognition/model.py`)

- Changes to `ROOM_CATEGORIES` or `_infer_external` affect every downstream
  output; expect and check corresponding diffs in `examples/`.
- Both IFC2x3 and IFC4 sample models must still load with the same element
  counts (`tests/test_pipeline.py::test_inventory`).
