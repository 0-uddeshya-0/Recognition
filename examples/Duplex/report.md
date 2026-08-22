# Compliance report — Duplex.ifc

**Status: FAIL** — 71 checks, 64 passed, 7 errors, 0 warnings. Ruleset: Residential baseline (demo) v0.1

| Rule | Severity | Checked | Failed |
|---|---|---|---|
| ROOM-MIN-AREA — Minimum floor area for habitable rooms | error | 12 | 0 |
| ROOM-MIN-WIDTH — Minimum clear width of habitable rooms | warning | 8 | 0 |
| DOOR-MIN-WIDTH — Minimum door leaf width | error | 14 | 6 |
| DOOR-MIN-HEIGHT — Minimum door leaf height | error | 14 | 0 |
| ROOM-DAYLIGHT — Glazing area as a share of floor area in habitable rooms | warning | 8 | 0 |
| ROOM-HAS-DOOR — Every room must be reachable through a door | error | 15 | 1 |

## Findings

| Rule | Sev | Element | Storey | Value | Limit | Message |
|---|---|---|---|---|---|---|
| DOOR-MIN-WIDTH | error | D-03 | Level 1 | 0.762 | 0.8 | D-03 M_Single-Flush:0762 x 2032mm:0762 x 2032mm:150173: leaf width 0.762 m < 0.8 m (interior) |
| DOOR-MIN-WIDTH | error | D-04 | Level 1 | 0.762 | 0.8 | D-04 M_Single-Flush:0762 x 2032mm:0762 x 2032mm:150257: leaf width 0.762 m < 0.8 m (interior) |
| DOOR-MIN-WIDTH | error | D-06 | Level 1 | 0.813 | 0.9 | D-06 M_Single-Glass 1:0813 x 2420mm:0813 x 2420mm:171853: leaf width 0.813 m < 0.9 m (external) |
| DOOR-MIN-WIDTH | error | D-01 | Level 1 | 0.813 | 0.9 | D-01 M_Single-Glass 1:0813 x 2420mm:0813 x 2420mm:171975: leaf width 0.813 m < 0.9 m (external) |
| DOOR-MIN-WIDTH | error | D-09 | Level 2 | 0.762 | 0.8 | D-09 M_Single-Flush:0762 x 2032mm:0762 x 2032mm:203720: leaf width 0.762 m < 0.8 m (interior) |
| DOOR-MIN-WIDTH | error | D-12 | Level 2 | 0.762 | 0.8 | D-12 M_Single-Flush:0762 x 2032mm:0762 x 2032mm:204034: leaf width 0.762 m < 0.8 m (interior) |
| ROOM-HAS-DOOR | error | R-07 | Level 1 |  |  | Room: no door found |
