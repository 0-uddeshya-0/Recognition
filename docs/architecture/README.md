# Recognition — system architecture

> **Thesis: the model plans, the code draws.**
> Devin never emits geometry and never states a regulation. It fills in a structured
> plan; deterministic code turns that plan into a building, and a deterministic rule
> engine judges the result.

Interactive version (diagrams, full tables): **https://claude.ai/code/artifact/7966e4e4-48d4-4909-b472-edaf00fd1b18**

| | |
|---|---|
| Geometry source of truth | IFC4 via IfcOpenShell |
| Compute | GitHub Actions (secrets stay server-side) |
| UI | Static, GitHub Pages, client-side IFC viewer |
| Jurisdiction (v1) | Bayern — BayBO Art. 45/46/48 + DIN 18040-2 |
| v1 input | Natural language → 2D + 3D. Sketch → 3D is phase 8. |

Related: [autonomy.md](autonomy.md) · [studio.md](studio.md) · [contracts.md](contracts.md) · [regulations.md](regulations.md) · [adr/](adr/)

> **Autonomy note.** The interview in L1 below is described as interactive. It is not:
> it runs *before* the trigger and produces a sealed brief, after which the run reaches
> merged artifacts with nobody in the middle and no approval step. See
> [autonomy.md](autonomy.md), which supersedes L1's position.

---

## 1. The five sources of truth

Everything else in the repository is *derived* and may be deleted and regenerated.
**Nothing derived is ever hand-edited** — not by a human, not by Devin.

| # | Authority over | Artifact | Written by | Hard rule |
|---|---|---|---|---|
| SoT-1 | **Intent** | `briefs/<project>.json` | Interview agent, confirmed by user | Never silently inferred; unconfirmed values become recorded `assumptions[]` |
| SoT-2 | **Regulation** | `rules/by/*.yaml` | A human curator, with citation | No LLM may author, edit or extend a rule |
| SoT-3 | **Geometry** | `design/<project>.py` | The deterministic translator | The only editable geometry artifact |
| SoT-4 | **Exchange** | `out/model.ifc` | IfcOpenShell, from SoT-3 | Pure output; regenerated every run |
| SoT-5 | **Provenance** | git history + Entire checkpoints | git hooks | Append-only |

Why the Python DSL and not the IFC is the geometry truth: an IFC diff is unreadable and an
agent editing IFC directly can produce a file that parses but is architecturally nonsense.
The DSL is ~40 readable lines for a six-room house, every number is a dimension in metres,
and a diff shows exactly what moved. That reviewability *is* the safety mechanism.
See [ADR-0001](adr/0001-geometry-source-of-truth.md).

---

## 2. Layers

Numbering is a real dependency order: L*n* may only read artifacts produced by L*<n*.

### L0 — Jurisdiction packs & project seed · *no model*

A jurisdiction pack is a directory of YAML declaring the rules in force for one place and
one building class, versioned and reviewed like code. Each pack also declares its own
**data requirements** (`requires:`), which is what drives the interview in L1 — so adding a
rule automatically adds a question and no question bank is hand-maintained.

- **emits** Ruleset object, required-slot manifest
- **libraries** PyYAML, pydantic
- **fails when** a rule lacks `source` or `tier` → load error, hard stop

### L1 — Intake & intent, the interview · *LLM, cheap*

Converts prose into a typed `DesignBrief` by slot-filling, asking MCQs with a free-text
escape on every one. **Which slots are missing is computed in Python** from the L0
manifest; the model's only job is phrasing. Full mechanism in §4.

- **emits** `briefs/<p>.json` (SoT-1), `questions[]`, `assumptions[]`
- **libraries** pydantic, Devin API
- **fails when** a returned value falls outside the slot enum/range → rejected and re-asked, never coerced

### L2 — Plan synthesis, the architect · *LLM, strongest, temp 0*

`DesignBrief` in, `ArchitectPlan` out: storeys, rooms with target areas and categories, an
adjacency graph, a circulation spine, opening intents. **No coordinates** — the architect
reasons in relationships and areas; metres are L3's job.

Architectural knowledge lives here as retrievable skill files, not model memory: room-size
*Richtwerte*, adjacency conventions (bath reached from the hall, not through a bedroom),
daylight orientation, circulation width, structural span limits.

The plan is **pre-checked before geometry exists** — target areas are tested against the
ruleset immediately, so "bedroom 6 m² but you asked for barrier-free" costs one cheap call
instead of a full geometry round-trip.

- **reads** `DesignBrief` only — never the chat transcript
- **emits** `plans/<p>.json`, `rationale.md`
- **libraries** pydantic, networkx
- **fails when** adjacency graph disconnected or areas exceed the footprint → returned with the specific violation

### L3 — Deterministic translation · *0 tokens, pure code*

The heart of the anti-hallucination design, proven by
[Pan-Chera/Multi-Agent-CAD](https://github.com/Pan-Chera/Multi-Agent-CAD) (MIT): a plain
Python function turns the typed plan into DSL source at zero token cost.

`recognition/translate.py` runs rectangular floor-packing over the adjacency graph, derives
wall centre-lines from room boundaries, snaps to a 5 cm grid, and places openings where the
plan asked. Constructs it cannot express emit a `# TODO_AGENT:` marker with the plan
fragment attached — **only those markers are ever sent to a model.**

- **emits** `design/<p>.py` (SoT-3)
- **libraries** shapely, networkx, rectpack, black (so diffs stay clean)
- **fails when** packing cannot satisfy the adjacency graph → infeasibility report back to L2, never a broken plan

See [ADR-0002](adr/0002-deterministic-translator.md).

### L4 — Geometry kernel & artifacts · *no model*

Executing the DSL builds real IFC4: `IfcWall` with extruded solids, `IfcSpace` carrying
name/category/area, `IfcDoor`/`IfcWindow` cut through proper `IfcOpeningElement`s.
Semantics matter — a compliance engine must ask "what is the net floor area of this
bedroom", which a mesh cannot answer. Everything else is a serializer off that one IFC.

- **emits** `model.ifc`, `sheets/*.{svg,pdf,png,dxf}`, `model.glb`, `schedules/*.csv`
- **libraries** ifcopenshell, shapely, svgwrite, cairosvg, ezdxf, IfcConvert
- **fails when** solids self-intersect or an opening misses its wall → assertion, non-zero exit

### L5 — Verification, the arbiter · *the gate*

Four independent deterministic checks. Devin's work is finished when this layer is green,
not when Devin says so.

1. **Regulation** — `recognition/rules.py` emits one result per element checked, pass *or*
   fail, so coverage is visible alongside violations.
2. **Data completeness** — `ifctester` validates against a buildingSMART **IDS** file:
   are the properties a checker needs actually present? Catches "the rule passed because
   the data was missing".
3. **Geometry sanity** — shapely: no overlapping rooms, no room without a door, envelope
   closed, no wall floating free.
4. **Regression** — pytest over committed examples; output is deterministic, so an
   unexplained diff in an untouched sheet *is* the bug signal.

- **fails when** any `tier: law` rule fails → merge blocked. Guidance-tier failures inform, never block.

### L6 — Iteration, options & edit · *LLM, router*

"Make the Schlafzimmer at least 25 m²" is ambiguous by design. A small classifier routes
the request to the **lowest layer that can satisfy it**; it re-enters there, never at the top.

| Request kind | Example | Re-enters at | Cost |
|---|---|---|---|
| Rule change | "bedrooms must be ≥ 25 m² under the new code" | L0 — edit YAML, re-run L5 | seconds, no model |
| Design change | "make the Schlafzimmer at least 25 m²" | L2 — amend plan, re-translate | one strong call |
| Local geometry | "move that wall 600 mm west" | L3 — patch the DSL | zero model |
| Drawing only | "show dimensions in cm" | L4 — drawing config | zero model |

**Options as branches.** When several strategies satisfy a request, each becomes its own git
branch with its own sheets, compliance result and cost estimate. Choosing one merges it;
the others stay in history.

### L7 — Presentation · *no server*

GitHub Pages serves static files only. Meshing happens at *artifact* time
(`recognition/mesh.py` triangulates via ifcopenshell into `mesh.json`, tags and
areas included), so the browser just draws with three.js — no IFC parsing at
view time; web-ifc was considered and dropped for exactly this reason (see
[studio.md](studio.md)). 2D sheets are already vector SVG. **The page never
holds a secret**: live actions (the Devin interview, dispatching a run) go
through GitHub Actions with the viewer's own token, and the key stays a
repository secret.

### L8 — Orchestration & provenance · *infra*

GitHub Actions is the runtime. Devin is invoked from inside a workflow where the API key
lives as a repository secret. Entire captures every agent session and binds it to the commit
it produced, so any line of a generated drawing traces back to the conversation that caused
it. See [ADR-0004](adr/0004-runtime-topology.md).

---

## 3. Agent roster

Each stage reads **only the previous stage's structured JSON — never the conversation
history**. On MAC's benchmark that single discipline cut total tokens 116× and *raised* the
pass rate to 99.3%, because a model that cannot see a transcript cannot drift with it.

| Role | Layer | Reads exactly | Writes | Model | Temp |
|---|---|---|---|---|---|
| Interviewer | L1 | user turn + slot manifest + brief-so-far | `DesignBrief`, `questions[]` | cheap | 0.3 |
| Architect | L2 | `DesignBrief` + architect skill files | `ArchitectPlan`, rationale | strongest | 0.0 |
| Translator | L3 | `ArchitectPlan` | `design/*.py` | **none** | — |
| Repairer (Devin) | L5→L3 | QA report + DSL reference + failing file | patch, branch, PR | Devin | — |
| Explainer | L6 | `summary.json` + the diff | human-readable change note | cheap | 0.4 |

**Why Devin only as Repairer.** Devin's strength is the long autonomous repo loop: clone,
install, run tests, read the failure, patch, push, open a PR. That is exactly this role and
nothing else in the pipeline. The Interviewer and Architect are short structured-output
calls — cheaper and more controllable as direct API calls.

---

## 4. The interview: a grill that cannot invent

Questions are generated from the ruleset's declared data requirements, and the gap analysis
is Python.

```yaml
# rules/by/residential.yaml
- id: BF-TRIGGER-ART48
  title: Barrier-free dwellings required
  tier: law
  source:
    law: BayBO Art. 48 (1)
    url: https://www.gesetze-bayern.de/Content/Document/BayBO-48
    retrieved: 2026-08-22
  requires: [dwelling_count, storey_count]   # ← drives the interview
  when: dwelling_count > 2
  then: { require_ruleset: din-18040-2 }
```

At interview time the engine computes `needed = ⋃ rule.requires`, subtracts what the brief
holds, and asks about the difference. Add a rule tomorrow and the interview covers it the
same day.

**Four question forms** — `single` (closed enum, so an out-of-set answer is impossible),
`multi` (from the room-category vocabulary already in `model.py`), `number` (with unit and
plausible range), and `free` text, which is available on every question.

**Stopping rule**
1. Stop when no **blocking** slot is empty — blocking = required by a `tier: law` rule.
   Legal inputs are never assumed.
2. Cap at 3 rounds, ≤ 4 questions per round.
3. Every non-blocking slot still empty is written to `assumptions[]` with its default, basis
   and confidence, then rendered in the UI as an editable chip.

The assumption register is the honesty surface: the failure mode of design agents is the
silent guess — the model picks 2.50 m ceilings, never mentions it, and the client finds out
in the drawing.

---

## 5. Eight mechanisms against hallucination

"Don't hallucinate" is not a prompt instruction; it is an architecture.

| # | Mechanism | Removes the risk that… | Where |
|---|---|---|---|
| 1 | Model never emits geometry | a plausible-looking wall coordinate is invented | L3 |
| 2 | Model never states a regulation — only cites an existing rule ID | a confidently wrong legal claim reaches the client | L0/L6 |
| 3 | Rules carry provenance — article, URL, retrieval date, tier | guidance is presented as statute | L0 |
| 4 | Blind spots declared — `checkable: no` reports "not evaluated" | absence of data reads as compliance | L5 |
| 5 | Gap analysis is code; the model only phrases questions | a required legal input is quietly assumed | L1 |
| 6 | Assumption register — every inferred value surfaced and editable | a silent default becomes an invisible decision | L1/L7 |
| 7 | Structured state passing — no stage re-reads the transcript | an early misreading compounds across turns | L1→L5 |
| 8 | Deterministic verifier gate decides "done", not the agent | "I've fixed it" is accepted without evidence | L5 |

---

## 6. Libraries

### Adopted

| Library | Licence | Layer | Job |
|---|---|---|---|
| [ifcopenshell](https://github.com/IfcOpenShell/IfcOpenShell) 0.8.5 | LGPL-3.0 | L4/L5 | Build and read IFC4 |
| [ifctester](https://pypi.org/project/ifctester/) 0.8.5 | LGPL-3.0 | L5 | Validate against a buildingSMART IDS |
| shapely | BSD-3 | L3/L4/L5 | All 2D geometry |
| [ezdxf](https://github.com/mozman/ezdxf) | MIT | L4 | DXF export for AutoCAD/Revit |
| svgwrite + cairosvg | MIT / LGPL | L4 | Sheets, then SVG → PDF/PNG |
| pydantic | MIT | L1/L2 | Typed contracts, validated at the boundary |
| networkx | BSD-3 | L2/L3 | Adjacency and circulation graphs |
| [web-ifc](https://github.com/ThatOpen/engine_web-ifc) + three.js | MPL-2.0 / MIT | L7 | Parse and render IFC **in the browser** |
| pytest | MIT | L5 | The regression half of the gate |

### Patterns borrowed (not dependencies)

- **[Pan-Chera/Multi-Agent-CAD](https://github.com/Pan-Chera/Multi-Agent-CAD)** (MIT, 869★) —
  zero-token deterministic translator; structured-state handoff instead of context replay;
  every intermediate artifact written to disk for audit.
- **[CubiCasa5k](https://github.com/CubiCasa/CubiCasa5k)** — dataset behind the phase-8
  sketch→plan path. Licence `NOASSERTION`; resolve before redistribution.
- **[Raster-to-Graph](https://github.com/SizheHu/Raster-to-Graph)** — autoregressive graph
  reconstruction from a raster plan. Outputs a *graph*, which lands directly on our
  `ArchitectPlan` shape rather than pixels. Best phase-8 candidate.

### Considered and rejected

| Option | Verdict | Reasoning |
|---|---|---|
| [OpenSCAD](https://github.com/openscad/openscad) | **not adopted** | Mesh CSG, no B-rep, and decisively **no semantics** — a union cannot tell you a room's category or net floor area, which is exactly what compliance needs. Also a separate non-Python language for capability IFC already covers. |
| [CadQuery](https://github.com/cadquery/cadquery) / [build123d](https://github.com/gumyr/build123d) | **phase 3, scoped** | Excellent OCCT B-rep kernels — for *parts*, not buildings. Right tool to detail a stair or window joinery to STEP for fabrication. Wrong as the building's source of truth: no `IfcSpace`, no storey structure, no property sets. Keep as a component sub-kernel imported into IFC. |
| Hand-authored IFC by the model | rejected | The original hallucination surface: unreviewable diffs, parseable-but-nonsense output. |
| RAG over statute PDFs for compliance | rejected | Retrieval returns *text about* a rule; checking a building needs an *executable predicate* over geometry. Retrieval stays useful for explaining a rule to a human — never for deciding pass/fail. |

---

## 7. Build order

| Phase | Deliverable | Layers | Depends on |
|---|---|---|---|
| **0** | Fix the ruleset: `tier` + `source` on every rule, daylight → 1/8, demote `ROOM-MIN-AREA` to guidance | L0 | nothing — this is a correctness bug |
| 1 | Typed contracts: `DesignBrief` + `ArchitectPlan` pydantic models + fixtures | L1/L2 | 0 |
| 2 | The translator — plan → `design/*.py`, zero tokens, packing tests | L3 | 1 |
| 3 | Interview engine: slot manifest from `requires`, MCQ generation, assumption register | L1 | 0–1 |
| 4 | IDS spec + `ifctester` in the gate; coverage incl. not-evaluated | L5 | 0 |
| 5 | Actions workflow: dispatch → pipeline → commit; Devin as Repairer | L8 | 2–4, **write-access blocker** |
| 6 | Static UI on Pages with web-ifc viewer, four states | L7 | 5 |
| 7 | Options-as-branches | L6 | 6 |
| 8 | Sketch → plan via Raster-to-Graph onto the same `ArchitectPlan` | L1′ | 2 |

---

## 8. Risks

> **Resolved by design — Devin no longer needs write access.** The 403 that blocked the
> early runs was routed around architecturally: sessions return an `ArchitectPlan` and never
> touch the repository; deterministic code builds the artifacts and the Actions workflow
> commits them. See [autonomy.md](autonomy.md) § "Why a model cannot fake a pass".

| Risk | Severity | Mitigation |
|---|---|---|
| **Floor-packing is the hard part** — adjacency graph → sensible rectangular layout is a real algorithmic problem | high | Constrain v1 to rectangular single-storey envelopes on an orthogonal grid. Let the Architect propose the bay structure rather than solving general packing. |
| **Legal exposure** — anything resembling a compliance certificate invites reliance | high | Tiers, citations, declared blind spots, and a persistent line on every sheet: a design aid, not a *Prüfstatiker*. Never the word "certified". |
| **Actions latency** — minutes per iteration is poor for a design conversation | medium | L3/L4/L5 are seconds locally; run them in-process for edits, reserve Actions for Devin work. |
| **Ruleset drift** — a stale citation is worse than none | medium | `retrieved:` on every rule; scheduled job flags citations older than 12 months. |
| CubiCasa5k licence is `NOASSERTION` | medium | Resolve before phase 8. |
| ifcopenshell is LGPL-3.0 | low | Fine as an imported, unmodified Python library. |

### Still open

- **Multi-storey.** v1 is single-storey. Stairs, vertical circulation and floor alignment are
  a genuine second problem, not an increment.
- **Who is the client?** An architect wants DXF/IFC and control; a homeowner wants pictures
  and a price. The four UI states lean professional.
- **Cost model.** The €1,400 / €2,100 / €600 estimates in the options view need a real rate
  table with a stated basis, or should be dropped rather than shown unsourced.
