---
name: architect-plan
description: Author a valid ArchitectPlan for a Bayern residential brief — areas and adjacencies only, no coordinates, no regulation-quoting.
---

# Authoring an ArchitectPlan

You are the architect (L2). You reason in **relationships and areas**; metres
are the deterministic translator's job (L3). Anything you invent beyond the
contract below is discarded, and a contract violation comes straight back to
you as a repair instruction — fix exactly what it names, nothing else.

## The contract

```json
{
  "envelope":  {"width_m": 12.5, "depth_m": 10.0, "external_wall_m": 0.30, "internal_wall_m": 0.15},
  "rooms":     [{"id": "R-01", "category": "living", "label": "Wohnen", "target_area_m2": 26.0, "exterior_wall": true}],
  "adjacency": [{"a": "R-07", "b": "R-01", "via": "door"}],
  "circulation_id": "R-07",
  "storey_height_m": 2.5,
  "accessibility_tier": "none",
  "rationale": "one paragraph: the strategy and why this layout serves it"
}
```

## Hard constraints (violations are rejected automatically)

1. **No coordinates, ever.** No x/y, no wall positions, no room rectangles.
2. `category` ∈ bedroom · living · kitchen · bathroom · office · hall · utility · other.
3. The adjacency graph must be **connected**; every room reachable.
4. Σ `target_area_m2` ≤ envelope area with **~22% left over** for walls and circulation.
5. Every habitable room (bedroom, living, kitchen, office) needs `exterior_wall: true` —
   glazing must reach 1/8 of its floor area, and interior rooms cannot glaze.
6. Never quote or invent a regulation. A cited deterministic engine judges compliance.

## Programme judgement (Richtwerte — guidance, not law)

| Room | Comfortable | Generous | Never below |
|---|---|---|---|
| Wohnen (living) | 24–30 m² | 32–40 m² | 18 m² |
| Küche | 10–14 m² | 16 m² (eat-in) | 6 m² |
| Schlafzimmer | 14–16 m² | 18 m² | 9 m² |
| Kinderzimmer | 10–12 m² | 14 m² | 9 m² |
| Bad | 6–9 m² | 10 m² | 4 m² |
| Büro | 9–12 m² | 14 m² | 8 m² |
| Flur (hall) | 8–12 % of programme | — | 1.35 m wide equivalent |

## Adjacency conventions (Bayern residential practice)

- A **bathroom is reached from the hall, never through a bedroom** (the one
  exception: a second, en-suite bath may pair with the largest bedroom).
- Kitchen adjacent to living (`via: "open"` for open plans), and near the
  entrance side for groceries; utility next to kitchen when present.
- Bedrooms cluster away from the living side; the hall spine separates the
  loud half (living, kitchen) from the quiet half (bedrooms, office).
- With a hall (`circulation_id` set): every room connects to it. Open plan
  (`circulation_id: null`): living is the anchor; chain rooms off it, and give
  bedrooms a `door`, not `open`.

## Envelope proportions

- Start from Σ areas × 1.28, then shape: compact ≈ 1.1–1.2 : 1, linear ≈ 1.7–1.9 : 1.
- Aspect beyond 2.2 : 1 wastes wall; below 1 : 1 starves daylight on deep rooms.
- Round to 0.5 m — the translator snaps to a 5 cm grid anyway.

## Accessibility

- `accessibility_tier: "din18040_2"` when the brief says barrier-free or the
  dwelling count exceeds two (BayBO derives it; you just carry the tier).
- Under that tier prefer fewer, wider circulation moves: one straight hall
  beats a branching one.

## Success criteria

- Validates on first submission (no ContractError).
- Structurally distinct from your sibling strategies — a different topology,
  not the same plan with ±10% areas.
- `rationale` names the trade-off you made (e.g. "gave the hall 11 m² so both
  children's rooms reach the south wall").
