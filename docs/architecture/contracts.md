# Typed contracts

The handoffs between layers. Every one is a pydantic model, validated **at the boundary** —
a malformed plan never reaches the translator, and a model that returns an out-of-enum value
is re-asked rather than coerced.

Rule: each stage reads only the previous stage's artifact. No stage re-reads the transcript.

```
user turn ──▶ DesignBrief ──▶ ArchitectPlan ──▶ design/*.py ──▶ model.ifc ──▶ ComplianceReport
   L1            SoT-1            (typed)          SoT-3          SoT-4          (gate)
```

---

## `DesignBrief` — SoT-1, written by L1

What the client wants, in typed slots. Produced by the interview; the only input L2 reads.

```jsonc
{
  "schema": "designbrief/v1",
  "project": "haus-am-hang",
  "created": "2026-08-22T14:00:00Z",

  "site": {
    "bundesland": "BY",              // enum — selects the jurisdiction pack
    "plot": { "width_m": 18.0, "depth_m": 24.0 },
    "orientation_deg": 168           // street-facing normal, for daylight reasoning
  },

  "programme": {
    "building_class": "detached_house",   // enum
    "dwelling_count": 1,                  // BLOCKING — triggers BayBO Art. 48 above 2
    "storey_count": 1,                    // BLOCKING — 1 or 2; at 2 the engine stacks
    "occupants": 4,
    "rooms": [                            // categories from recognition/model.py
      { "category": "bedroom",  "count": 2, "min_area_m2": null },
      { "category": "living",   "count": 1, "min_area_m2": 26.0 },
      { "category": "kitchen",  "count": 1 },
      { "category": "bathroom", "count": 1 },
      { "category": "office",   "count": 1 }
    ]
  },

  "accessibility": {
    "tier": "none"                   // none | din18040_2 | din18040_2_R
  },                                 // forced to din18040_2 when dwelling_count > 2

  "assumptions": [
    {
      "slot": "storey_height_m",
      "value": 2.50,
      "basis": "BayBO Art. 45 (1) minimum 2.40 m + 100 mm floor build-up",
      "confidence": "high",
      "confirmed": false             // renders as an editable chip in the UI
    }
  ],

  "open_questions": [],              // non-blocking items the client skipped
  "blocking_missing": []             // MUST be empty before L2 runs
}
```

**Invariants**
- `blocking_missing == []` is a hard precondition for L2. Enforced in code, not by prompt.
- Every value not supplied by the client appears in `assumptions[]`. There is no third
  category — a value is either confirmed or declared as an assumption.
- `accessibility.tier` is *derived*, never asked directly, when `dwelling_count > 2`.

---

## `ArchitectPlan` — written by L2, read by L3

Relationships and areas. **No coordinates** — turning this into metres is L3's job, and
keeping coordinates out of the model's reach is anti-hallucination mechanism #1.

```jsonc
{
  "schema": "architectplan/v1",
  "brief": "haus-am-hang",

  "envelope": {
    "shape": "rectangle",            // v1 constraint — see Risks
    "width_m": 12.0,
    "depth_m": 10.0,
    "wall_thickness": { "external_m": 0.30, "internal_m": 0.15 }
  },

  "storeys": [
    {
      "name": "Erdgeschoss",
      "elevation_m": 0.0,
      "height_m": 2.50,

      "rooms": [
        { "id": "R-01", "category": "kitchen",  "label": "Küche",        "target_area_m2": 16.3, "exterior_wall": true },
        { "id": "R-02", "category": "living",   "label": "Wohnen",       "target_area_m2": 26.0, "exterior_wall": true },
        { "id": "R-03", "category": "hall",     "label": "Flur",         "target_area_m2": 11.5, "exterior_wall": false },
        { "id": "R-04", "category": "bedroom",  "label": "Schlafzimmer", "target_area_m2": 22.1, "exterior_wall": true }
      ],

      "adjacency": [                 // validated as a connected graph by networkx
        { "a": "R-03", "b": "R-01", "via": "door" },
        { "a": "R-03", "b": "R-04", "via": "door" },
        { "a": "R-01", "b": "R-02", "via": "open" }
      ],

      "circulation": { "spine": "R-03", "min_width_m": 1.20 },

      "openings": [                  // intent only — L3 places them
        { "room": "R-04", "kind": "window", "target_glazing_ratio": 0.125,
          "basis": "BayBO Art. 45 (2)" },
        { "room": "R-02", "kind": "door", "external": true, "label": "Terrassentür" }
      ]
    }
  ],

  "rationale": "Sleeping wing north-east away from the street; living and kitchen share the south façade for daylight; bath reached from the hall, never through a bedroom.",
  "todo_agent": []                   // constructs the translator cannot express
}
```

**Invariants**
- Adjacency must form a connected graph. Disconnected → returned to L2 with the specific
  violation, never passed on.
- `Σ target_area_m2` + circulation + wall footprint ≤ envelope area. Checked before L3.
- Target areas are pre-checked against the ruleset **here**, before any geometry exists —
  cheap early verification.
- `openings[].basis` cites a rule ID or article. A glazing ratio with no basis is a bug.

---

## `ComplianceReport` — written by L5

One result per element checked, **pass as well as fail**, so coverage is visible alongside
violations. This is what makes "not evaluated" reportable.

```jsonc
{
  "schema": "compliance/v1",
  "ruleset": { "name": "Bayern residential", "version": "1.0", "retrieved": "2026-08-22" },
  "model": "out/model.ifc",

  "summary": {
    "checked": 27,
    "passed": 27,
    "failed": 0,
    "not_evaluated": 2,              // NEVER hidden — see regulations.md
    "blocking_failures": 0           // only tier:law counts here
  },

  "results": [
    {
      "rule_id": "ROOM-DAYLIGHT",
      "tier": "law",
      "severity": "error",
      "element": { "tag": "R-04", "name": "Schlafzimmer", "storey": "Erdgeschoss" },
      "value": 0.128, "limit": 0.125, "passed": true,
      "message": "Glazing 2.83 m² ÷ floor 22.1 m² = 0.128 ≥ 1/8",
      "source": {
        "law": "BayBO Art. 45 (2)",
        "url": "https://www.gesetze-bayern.de/Content/Document/BayBO-45",
        "retrieved": "2026-08-22"
      }
    },
    {
      "rule_id": "SMOKE-DETECTOR",
      "tier": "law",
      "status": "not_evaluated",
      "reason": "No smoke-detector data in the IFC model.",
      "source": { "law": "BayBO Art. 46 (4)" }
    }
  ]
}
```

**Invariants**
- Every result carries `source`. A finding without a citation cannot be rendered.
- `not_evaluated` is a first-class status, never silently dropped and never counted as a pass.
- Only `tier: law` (and triggered `tier: standard`) contribute to `blocking_failures`.
  Guidance never blocks a merge.

---

## Question payload — L1 → UI

```jsonc
{
  "round": 1,
  "questions": [
    {
      "slot": "dwelling_count",
      "blocking": true,
      "why": "BayBO Art. 48 (1) requires barrier-free dwellings above 2 units.",
      "form": "number",
      "unit": "dwellings",
      "range": [1, 12]
    },
    {
      "slot": "accessibility.tier",
      "blocking": false,
      "why": "Determines whether DIN 18040-2 door and corridor rules apply.",
      "form": "single",
      "options": [
        { "value": "none",            "label": "Not required" },
        { "value": "din18040_2",      "label": "Barrier-free (DIN 18040-2)" },
        { "value": "din18040_2_R",    "label": "Wheelchair tier R" }
      ]
    }
  ],
  "free_text_always_available": true
}
```

`why` is mandatory and is generated from the rule that declared the slot in `requires:` —
the client always learns which regulation is driving the question.
