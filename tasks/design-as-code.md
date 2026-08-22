# Design as code — the building itself in Python

## Why

Today the IFC is read-only. Recognition turns it into paperwork (plans, schedules, a code
check) and Devin can change *how that paperwork is made* — rules, drawings, vocabulary.
What Devin cannot do is change the **building**: if a bedroom is 22 m² and the code wants
25, we say FAIL and stop there.

If the building itself is code, Devin can move the wall. Every design option becomes a
branch; the architect compares drawings and picks one. That is the full version of
"architecture as code".

## What it is

A round trip:

```
house.ifc ──parse──► house.py ──edit (Devin or a person)──► house.py' ──build──► house'.ifc ──recognition run──► plans + check
```

`house.py` reads like a plan, not like geometry:

```python
from recognition.design import House

h = House("AC20-FZK-Haus")

eg = h.storey("Erdgeschoss", elevation=0.0, height=2.5)
eg.wall((0.0, 0.0), (12.0, 0.0), thickness=0.30, external=True)          # W1, south
eg.wall((12.0, 0.0), (12.0, 10.0), thickness=0.30, external=True)        # W2, east
eg.wall((5.0, 0.3), (5.0, 5.1), thickness=0.15)                          # W5, kitchen / living
eg.room("Küche",  [(0.3, 0.3), (4.9, 0.3), (4.9, 5.1), (0.3, 5.1)])      # category inferred: kitchen
eg.room("Wohnen", [(5.1, 0.3), (11.7, 0.3), (11.7, 5.1), (5.1, 5.1)])
eg.door(on="W5", at=2.0, width=0.885, height=2.01, name="Innentuer-1")
eg.window(on="W1", at=1.5, width=2.0, height=1.2, sill=0.9, name="EG-Fenster-4")

h.write("out/house.ifc")
```

Half of this already exists: `recognition/model.py` extracts exactly these things (walls with
thickness and external flag, room outlines, doors and windows with host wall, size and
position) from any IFC. The new parts are **emit** (model → `house.py`) and **build**
(`house.py` → IFC, with `ifcopenshell.api`). The existing pipeline then runs on the result
unchanged.

## Honest limit: it is lossy

`house.py` keeps what plans and rules need — storeys, walls, rooms, doors, windows — and
drops everything else: roof shape, slabs, stairs, furniture, materials, curved geometry,
MEP. The rebuilt IFC is a **proposal of the layout**, not a replacement for the architect's
file. The architect reviews it as drawings and applies the accepted change in their own
tool (or imports the variant). Never overwrite the uploaded IFC; a variant is a new file.

For the sample models (straight walls, rectangular rooms) the loss is irrelevant.

## The PoC

1. `recognition/design.py` — the `House` / `Storey` API above, and `House.write()` via
   `ifcopenshell.api`: IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey; IfcWall as
   an extruded rectangle; IfcSpace as an extruded outline; IfcDoor / IfcWindow filling an
   IfcOpeningElement in the host wall. Units metres, IFC4.
2. `recognition decompile model.ifc house.py` — read with `model.load`, emit the script.
   Deterministic: same IFC → same file, so edits diff cleanly in git.
3. `recognition build house.py out.ifc` — run the script, write the IFC.
4. Round-trip test on FZK and Duplex: decompile → build → `recognition run` gives the same
   counts (FZK: 13 walls, 7 rooms, 5 doors, 11 windows), the same tags, and the same
   compliance status. Areas within 2 %.
5. The demo: FZK with `bedroom: 25.0` fails on R-04. Devin is asked *"make the
   Schlafzimmer at least 25 m²"*, edits `house.py` (moves one wall), builds, runs the
   pipeline, opens a PR with the new plan: FAIL → PASS. Playbook: `playbooks/design-change.devin.md`.
6. UI: a job whose source is an IFC also shows its `house.py` (read-only, collapsible) and
   "Request a change" can now be a design change — Devin decides whether to edit the rules,
   the generator, or the house.

## Acceptance

- [ ] `uv run recognition decompile samples/AC20-FZK-Haus.ifc out/fzk.py && uv run recognition build out/fzk.py out/fzk.ifc && uv run recognition run out/fzk.ifc out/fzk-rt` works and reports PASS with the same counts as the original.
- [ ] Same for Duplex (IFC2x3 in, IFC4 out is fine), same seven findings.
- [ ] `out/fzk.py` is readable: a person can find "the wall between Küche and Wohnen" in under a minute.
- [ ] Editing one room outline by hand and rebuilding changes the area on the sheet and in `rooms.csv`.
- [ ] One Devin session performs the FAIL → PASS demo end to end (needs GitHub write access for the Devin app).
- [ ] `uv run pytest -q` green; round-trip tests added to `tests/test_design.py`.

## Non-goals (this PoC)

- Curved or sloped walls, roofs, slabs, stairs, furniture, materials, MEP.
- Generating layouts from scratch, optimising, or judging architecture.
- Costs and quantities (next: a quantity-takeoff schedule × unit-rate YAML).
- FreeCAD. It is a good *editor and viewer* for `house.py` later (Arch workbench, Python
  API, headless export), but the round trip does not need it and Devin's VM stays light
  without it.

## After the PoC

- **Variants:** one request → N parallel Devin sessions → N branches → a comparison
  screen: plans side by side, compliance, areas, later cost.
- **Cost:** quantities from the model (wall m², glazing m², door count) × a rate table.
- **One repo per building project:** `house.py`, rules, deliverables and history together;
  Recognition as a dependency; Devin as that project's detailer.

## Process

Branch `poc/design-as-code` from `ui/poc`. Commit after: `design.py` build → decompile →
round-trip tests → CLI → playbook → UI hook. PR against `ui/poc` with before/after plans of
the FZK demo. Time box: one day.
