# The regulation model

> **This is a design aid, not legal advice, and not a substitute for a *Prüfstatiker* or a
> submitting architect.** Nothing here is certified. Rule summaries are the project's own
> reading of the cited articles.

Compliance is worthless if the system cannot say *why* a rule exists and *whether it may
block*. Two mechanisms carry that: **provenance tiers** and **declared blind spots**.

---

## 1. Two corrections needed in the current ruleset

Found while auditing `rules/residential.yaml` on `poc/ifc-detailing`. Both are phase-0 work.

### ① `ROOM-DAYLIGHT` uses the wrong ratio

```yaml
# current
- id: ROOM-DAYLIGHT
  params: { min_ratio: 0.10 }
```

BayBO Art. 45 (2) requires the window opening to be **≥ 1/8 = 0.125** of the room's net
floor area. The project's own research table already recorded this ("today we use 10 %, real
is 12.5 %"); the code was never updated. A room at 0.11 currently passes and should not.

### ② `ROOM-MIN-AREA` claims legal authority it does not have

```yaml
# current
- id: ROOM-MIN-AREA
  severity: error          # ← blocks a merge
  params: { bedroom: 9.0 }
```

BayBO sets **no minimum bedroom area**. It governs clear height (Art. 45 (1)) and daylight
(Art. 45 (2)). The 9 m² figure is a *Richtwert* — useful guidance from planning literature,
not statute. Blocking on it makes the system assert a legal requirement that does not exist,
which is exactly the failure mode this architecture is built to prevent.

Fix: demote to `tier: guidance`, severity `warning`, never blocking.

---

## 2. Provenance tiers

Every rule must declare a `tier`. The tier decides whether it may block.

| Tier | Means | Example | Severity ceiling | Can block? |
|---|---|---|---|---|
| `law` | a cited statute article | BayBO Art. 45 (1) — 2.40 m clear height | error | **yes** |
| `standard` | a DIN norm, binding once triggered or opted into | DIN 18040-2 — 90 cm door clear width | error *when triggered* | only if triggered |
| `guidance` | published *Richtwerte*, professional convention | bedroom ≈ 9–14 m² | warning | **never** |
| `house` | this practice's own preference | hallway ≥ 1.2 m for furniture moves | info | **never** |

Required shape of a rule:

```yaml
- id: ROOM-CLEAR-HEIGHT
  title: Minimum clear height of habitable rooms
  tier: law                        # REQUIRED — load fails without it
  severity: error
  source:                          # REQUIRED — load fails without it
    law: BayBO Art. 45 (1)
    url: https://www.gesetze-bayern.de/Content/Document/BayBO-45
    retrieved: 2026-08-22
  requires: [storey_height_m]      # drives the interview (see contracts.md)
  checkable: yes                   # yes | partial | no
  params:
    min_m: 2.40
    attic_min_m: 2.20
    attic_share: 0.5
```

A rule missing `tier` or `source` is a **load error, hard stop** — it cannot silently enter
the system.

---

## 3. The v1 Bayern pack

Sources: [BayBO Art. 45](https://www.gesetze-bayern.de/Content/Document/BayBO-45) ·
[Art. 46](https://www.gesetze-bayern.de/Content/Document/BayBO-46) ·
[Art. 48](https://www.gesetze-bayern.de/Content/Document/BayBO-48) ·
[DIN 18040-2 (doors)](https://nullbarriere.de/din18040-2-tueren.htm) ·
[BAK overview](https://en.bak.de/regulation/) · all retrieved 2026-08-22.

| Rule ID | Requirement | Source | Tier | Checkable from IFC? |
|---|---|---|---|---|
| `ROOM-CLEAR-HEIGHT` | habitable rooms ≥ 2.40 m clear; attic 2.20 m over half the area | BayBO Art. 45 (1) | law | **yes** — storey heights present |
| `ROOM-DAYLIGHT` | window opening ≥ **1/8** of net floor area | BayBO Art. 45 (2) | law | **yes** — glazing ÷ area |
| `DWELLING-FACILITIES` | each dwelling: kitchen or kitchenette, bath with tub/shower, WC | BayBO Art. 46 (1–2) | law | **yes** — room categories |
| `SMOKE-DETECTOR` | bedrooms, children's rooms, halls serving habitable rooms | BayBO Art. 46 (4) | law | **no** → *not evaluated* |
| `BF-TRIGGER-ART48` | > 2 dwellings → one storey's dwellings barrier-free | BayBO Art. 48 (1) | law | **yes** — dwelling count triggers the DIN pack |
| `DOOR-CLEAR-WIDTH` | ≥ 80 cm; tier R ≥ 90 cm; entrance ≥ 90 cm | DIN 18040-2 | standard | **yes** |
| `DOOR-CLEAR-HEIGHT` | ≥ 205 cm | DIN 18040-2 | standard | **yes** |
| `CORRIDOR-WIDTH` | ≥ 120 cm, with a 150 × 150 cm turning area at least once | DIN 18040-2 | standard | **yes** — hall footprints |
| `MOVEMENT-AREA` | 120 × 120 cm per room (tier R: 150 × 150) | DIN 18040-2 | standard | **partial** — approximated by narrowest room side, *declared* |
| `THRESHOLD` | ≤ 1 cm inside, ≤ 2 cm at the entrance | DIN 18040-2 | standard | **no** → *not evaluated* |
| `ROOM-MIN-AREA` | bedroom ≈ 9–14 m², living ≈ 18–30 m² | [Richtwerte](https://www.fertighaus.de/ratgeber/hausbau/grundriss-planen-richtwerte-fuer-raumgroessen/), not statute | guidance | **yes** — advisory only |
| `ROOM-HAS-DOOR` | every room reachable through a door | house convention | house | **yes** |

Further reading kept for the curator, not yet encoded:
[Baden-Württemberg barrier-free guide (PDF)](https://mlw.baden-wuerttemberg.de/fileadmin/redaktion/m-mlw/intern/Dateien/06_Service/Publikationen/Bauen_und_Wohnen/2022-02-22-BarriefreiesBauen-finale-LAY.pdf) ·
[AKNW Praxisleitfaden (PDF)](https://www.aknw.de/fileadmin/user_upload/News-PDFs/2021/07-2021/2021-07-12-Praxisleitfaden_Barrierefreies_Bauen_Wohnungen.pdf) ·
[WEKA DIN 18040-2 overview](https://www.weka.de/architekten-ingenieure/din-18040-2/).

---

## 4. Declared blind spots

`SMOKE-DETECTOR` and `THRESHOLD` cannot be evaluated from the model — there is no such data
in it. A system that quietly omitted them would report **PASS 27/27** and imply a
completeness it does not have.

Recognition instead reports them as `not_evaluated` with the reason, and every sheet carries
a coverage line:

```
27 checked · 2 not evaluated · 0 failed
```

**What the system cannot see is part of its output.** The UI must never render a bare PASS.

Three ways a blind spot resolves:
1. **Enrich the model** — add the property to the DSL and the IFC, then flip `checkable: yes`.
2. **Ask the client** — put the slot in `requires:` so the interview collects it as a
   declaration, recorded as an assumption rather than a measurement.
3. **Leave it declared** — legitimate for anything genuinely outside a geometric model.

---

## 5. Adding or changing a rule

1. Edit the YAML pack. **Never** encode a threshold in Python — thresholds are data.
2. Supply `tier`, `source` (with `retrieved`), `requires`, `checkable`. Load fails otherwise.
3. Implement the predicate as a `@rule("ID")` function in `recognition/rules.py` if it is new.
4. Add a fixture under `tests/fixtures/rules/` — one model that passes, one that fails.
5. Regenerate committed examples; inspect the diff. An unexpected change elsewhere is a bug.
6. `uv run pytest -q` must be green before the PR.

**No LLM may perform steps 1–2.** Devin may implement the predicate (step 3) and write tests,
because those are verifiable by execution. It may never author the threshold or the citation.

---

## 6. Drift control

A stale citation is worse than no citation. Every rule carries `retrieved:`; a scheduled job
flags any rule whose citation is older than 12 months for human re-verification. Re-checking
is a human task — the URLs are authoritative, the LLM's memory of them is not.
