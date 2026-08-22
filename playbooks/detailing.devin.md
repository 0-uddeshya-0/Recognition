# Playbook: produce or refresh a detailing package for an IFC model

Macro: `!detail`

## Procedure

1. Clone the repo, run `uv sync`, then `uv run pytest -q` to confirm a green baseline.
2. Obtain the model: use the attached `.ifc` file if one was provided, otherwise the path the user named. Copy it to `samples/<name>.ifc` only if the user says it should become a tracked sample; otherwise keep it under `out/` (git-ignored).
3. Run `uv run recognition run <model.ifc> out/<name> --project "<project name>"`.
4. Open every PNG under `out/<name>/sheets/` and read `out/<name>/report.md`. Look for: rooms with no label, door swings into walls, dimension chains with absurd values, rooms categorised as `other` that clearly are bedrooms/kitchens/etc.
5. If the model exposes a gap in the generator (a new room naming convention, a geometry case that renders wrongly, an IFC schema quirk), fix the generator in `recognition/`, add a test in `tests/`, regenerate `examples/` for both sample models, and re-run step 3.
6. If the user asked for a rule or convention change, edit `rules/*.yaml` or `drawings.SHEET/STYLE` — never the outputs — and cite the source of the new value in a YAML comment.
7. Commit on a branch named `detail/<name>` and open a PR.

## Specifications

- `uv run pytest -q` passes.
- The PR description contains: the compliance status line (`PASS`/`WARN`/`FAIL`, counts) for the target model, each generated sheet as an image, the full findings table from `report.md`, and a bullet list of assumptions.
- `examples/` is regenerated and committed if any generator file changed.
- The enriched IFC (`model.detailed.ifc`) is attached to the PR or placed where the user asked.

## Advice and pointers

- Room categories come from `recognition/model.py::ROOM_CATEGORIES`. Extending the keyword list is the usual fix for "all rooms are `other`".
- `IsExternal` is read from psets and otherwise inferred from the storey envelope. If exterior dimension chains look wrong, check `model._infer_external` before touching `drawings.py`.
- Door swings are a convention (into the room the door serves, hinge at the first jamb). The model does not encode real hinge sides; say so if a user asks for accuracy there.
- Keep thresholds in YAML. Python rule functions should only read `params`.
- Deterministic output is a feature: if a sheet you did not intend to change shows a diff, stop and find out why.

## Forbidden actions

- Editing `samples/*.ifc` or any file under `examples/` by hand.
- Reporting a rule as passed when it was not evaluated.
- Changing the tag numbering scheme without saying so in the PR title.
- Merging your own PR.

## Required from user

- The IFC model (attachment or path) and a project name.
- Optionally: jurisdiction or ruleset to apply (defaults to `rules/residential.yaml`, demo values).
