luka - test

## Testing

```bash
uv run pytest -q                                                   # whole suite, ~10 s
uv run pytest -q -k drawings                                       # one area
uv run pytest -q tests/test_pipeline.py::test_inventory            # one test
```

The suite is `tests/test_pipeline.py`: 10 end-to-end tests that run the real pipeline on the two committed sample models (`samples/AC20-FZK-Haus.ifc`, IFC4 and `samples/Duplex.ifc`, IFC2x3). No mocks — the IFC files are the fixtures.

| Area | What is asserted |
|---|---|
| Loading | Element counts per model (FZK: 13 walls, 7 spaces, 5 doors, 11 windows); external-wall inference finds the envelope even without `Pset_WallCommon.IsExternal`; tags (`R-xx`, `D-xx`) are identical across two loads |
| Schedules | Room schedule has one row per space with category, area (Wohnen ≈ 26 m²) and door connectivity |
| Rules | FZK passes with zero errors; Duplex fails `DOOR-MIN-WIDTH` on its 0.762 m doors; `rules/residential.yaml` only declares rule IDs the engine implements |
| Drawings | SVG contains the sheet number, room tags and title; PNG renders to a non-trivial file; DXF has the AIA layers (`A-WALL`, `A-DOOR`, `A-GLAZ`, `A-ANNO-DIMS`) and one swing arc per door on the storey |
| CLI | `run` writes the full package and `summary.json` reports `PASS`; `check` exits 0 on FZK and 1 on Duplex |

The tests assert invariants; they do not diff against `examples/`. Whether the committed output matches the generator is checked at review time (see `REVIEW.md`). Behaviour changes must come with a test, and a green run is a precondition for every PR — this is the gate Devin has to pass.
