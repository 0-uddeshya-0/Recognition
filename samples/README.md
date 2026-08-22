# Sample models

All files are public test models widely used in the IFC ecosystem. None were edited.

## Core samples (used by tests and `examples/`)

| File | Schema | Source | Notes |
|---|---|---|---|
| `AC20-FZK-Haus.ifc` | IFC4 | KIT / IAI, via [ibpsa/project1-wp-2-2-bim](https://github.com/ibpsa/project1-wp-2-2-bim) | 2-storey single-family house, 7 rooms. Small and legible — the demo model. Passes the demo ruleset. |
| `Duplex.ifc` | IFC2x3 | buildingSMART Duplex Apartment (Revit export), via [MadsHolten/BOT-Duplex-house](https://github.com/MadsHolten/BOT-Duplex-house) | 4 storeys, 2 mirrored units, 21 rooms. Fails the demo ruleset: six 0.762 m doors. |

## Extended samples (`samples/extended/`, not covered by tests)

| File | Schema | Source | Notes |
|---|---|---|---|
| `AC20-Smiley-West.ifc` | IFC4 | [KIT IFC examples](https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples) — "Smiley West" terraced houses | 10 identical row houses, 4 storeys, 140 rooms, 170 doors. Residential — the demo ruleset applies fully. ~17 s to process. |
| `AC20-Institute-Var-2.ifc` | IFC4 | [KIT IFC examples](https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples) — "Phantasy Office Building" | 5 storeys, 82 rooms (offices, labs, meeting rooms), 77 doors, 206 windows. Office — needs a non-residential ruleset to be meaningful. ~10 s. |

## Tested but not included (download on demand)

| Model | Where | Why not included |
|---|---|---|
| Revit sample "ARC" + "ARC_FireRatingAdded" (IFC4, 13 MB each) | [youshengCode/IfcSampleFiles](https://github.com/youshengCode/IfcSampleFiles) | Real Revit export but **no IfcSpace** (no rooms), so schedules and room rules are empty. The pair differs only by a FireRating property — a good fixture for a future data-completeness (IDS) check. |
| Schependomlaan "As Planned" + weekly revisions (IFC2x3, 14–62 MB) | [openBIMstandards/Archive-DataSetSchependomlaan](https://github.com/openBIMstandards/Archive-DataSetSchependomlaan) | Real built Dutch housing project with 4D planning data. Loads fine (879 walls in 21 s) but is a construction model: one storey, no rooms. Useful as a stress test, not for drawings. |
| `Ifc4_SampleHouse.ifc` (xBIM) | youshengCode/IfcSampleFiles | Tiny (5 walls). |
| buildingSMART PCERT sample scene | [buildingSMART/Sample-Test-Files](https://github.com/buildingSMART/Sample-Test-Files) | Trivial architecture (4 walls). |
