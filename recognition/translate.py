"""ArchitectPlan -> design DSL source. Deterministic, zero language-model tokens.

This module is the reason the system does not hallucinate geometry. The agent
supplies relationships and areas; every coordinate in the resulting building is
computed here, by code you can read, from numbers the agent had to justify.

The pattern is borrowed from Pan-Chera/Multi-Agent-CAD (MIT), whose deterministic
`_plan_to_code` translator carried most of its 116x token reduction *and* a higher
pass rate than the LLM-writes-code baseline. Determinism improved quality; it was
not a trade against it.

Layout algorithm
----------------
Squarified treemap over the interior rectangle. Rooms are placed in rows whose
aspect ratios are kept as close to 1 as possible, because a 1.2 x 18 m bedroom is
technically the right area and architecturally useless. Circulation is placed
first as a spine so every room can open onto it.

Everything snaps to a 5 cm grid: real buildings are dimensioned in round numbers,
and snapping keeps generated diffs stable across runs.

What it cannot express -- curved walls, split levels, non-rectangular envelopes --
becomes a `# TODO_AGENT:` marker carrying the plan fragment. Those markers are the
only geometry an agent is ever asked to write, and they show up in the diff.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .contracts import ArchitectPlan, RoomSpec

GRID = 0.05           # 5 cm
MIN_SIDE = 1.20       # a room narrower than this is not a room
MIN_DOOR_WALL = 1.00  # a shared edge shorter than this cannot host a door
# DIN 18040-2 wants 1.20 m of *clear* corridor. The spine is laid out on wall
# centre-lines and the room polygon is then inset by half a partition on each
# side, so the centre-line strip must carry a full wall thickness of slack or the
# finished corridor measures ~1.10 m and fails the very rule it was sized for.
CORRIDOR_CLEAR = 1.20
CORRIDOR_MIN = CORRIDOR_CLEAR + 0.15


def snap(v: float, grid: float = GRID) -> float:
    return round(round(v / grid) * grid, 3)


@dataclass
class Rect:
    """Axis-aligned room footprint in storey coordinates (x east, y north)."""
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def aspect(self) -> float:
        lo, hi = sorted((self.w, self.h))
        return hi / lo if lo > 0 else math.inf

    def polygon(self) -> list[tuple[float, float]]:
        return [(self.x, self.y), (self.x2, self.y), (self.x2, self.y2), (self.x, self.y2)]

    def snapped(self) -> Rect:
        x, y = snap(self.x), snap(self.y)
        return Rect(x, y, snap(self.x2) - x, snap(self.y2) - y)


class LayoutError(RuntimeError):
    """Packing could not satisfy the plan. Returned to L2, never passed downstream."""


# --------------------------------------------------------------------------
# Squarified treemap
# --------------------------------------------------------------------------

def _worst(row: list[float], side: float, scale: float) -> float:
    """Worst aspect ratio in a row laid along `side` (van Wijk et al.)."""
    if not row or side <= 0:
        return math.inf
    total = sum(row) * scale
    if total <= 0:
        return math.inf
    breadth = total / side
    return max(max(breadth / (a * scale / breadth) if a > 0 else math.inf,
                   (a * scale / breadth) / breadth if a > 0 else math.inf)
               for a in row)


def squarify(areas: list[float], rect: Rect) -> list[Rect]:
    """Lay out `areas` inside `rect`, keeping each cell as square as possible."""
    if not areas:
        return []
    scale = rect.area / sum(areas)
    out: list[Rect] = []
    free = Rect(rect.x, rect.y, rect.w, rect.h)
    remaining = list(areas)
    row: list[float] = []

    while remaining:
        side = min(free.w, free.h)
        candidate = row + [remaining[0]]
        if not row or _worst(candidate, side, scale) <= _worst(row, side, scale):
            row.append(remaining.pop(0))
            continue
        out.extend(_place_row(row, free, scale))
        free = _shrink(free, row, scale)
        row = []

    if row:
        out.extend(_place_row(row, free, scale))
    return out


def _place_row(row: list[float], free: Rect, scale: float) -> list[Rect]:
    total = sum(row) * scale
    cells: list[Rect] = []
    if free.w <= free.h:                      # lay the row horizontally
        height = total / free.w if free.w else 0.0
        x = free.x
        for a in row:
            w = (a * scale) / height if height else 0.0
            cells.append(Rect(x, free.y, w, height))
            x += w
    else:                                     # lay the row vertically
        width = total / free.h if free.h else 0.0
        y = free.y
        for a in row:
            h = (a * scale) / width if width else 0.0
            cells.append(Rect(free.x, y, width, h))
            y += h
    return cells


def _shrink(free: Rect, row: list[float], scale: float) -> Rect:
    total = sum(row) * scale
    if free.w <= free.h:
        height = total / free.w if free.w else 0.0
        return Rect(free.x, free.y + height, free.w, free.h - height)
    width = total / free.h if free.h else 0.0
    return Rect(free.x + width, free.y, free.w - width, free.h)


# --------------------------------------------------------------------------
# Plan -> rectangles
# --------------------------------------------------------------------------

def layout(plan: ArchitectPlan) -> dict[str, Rect]:
    """Assign every room an axis-aligned footprint inside the envelope.

    Circulation, if the plan names one, is laid out as a spine strip across the
    interior so that every other room has a boundary to open a door onto.
    """
    e = plan.envelope
    half = e.external_wall_m / 2.0
    inner = Rect(half, half, e.width_m - e.external_wall_m, e.depth_m - e.external_wall_m)
    if inner.w <= 0 or inner.h <= 0:
        raise LayoutError(
            f"envelope {e.width_m} x {e.depth_m} m is smaller than its own external walls"
        )

    rooms = list(plan.rooms)
    rects: dict[str, Rect] = {}

    spine = plan.circulation_id
    if spine and len(rooms) > 1:
        hall = plan.room(spine)
        others = [r for r in rooms if r.id != spine]
        # Spine runs along the longer axis; depth from its area, floored at a
        # width a person can actually pass through (DIN 18040-2 wants 1.20 m).
        if inner.w >= inner.h:
            depth = max(hall.target_area_m2 / inner.w, CORRIDOR_MIN)
            depth = min(depth, inner.h * 0.5)
            y = inner.y + (inner.h - depth) / 2.0
            rects[spine] = Rect(inner.x, y, inner.w, depth)
            bands = [Rect(inner.x, inner.y, inner.w, y - inner.y),
                     Rect(inner.x, y + depth, inner.w, inner.y2 - (y + depth))]
        else:
            depth = max(hall.target_area_m2 / inner.h, CORRIDOR_MIN)
            depth = min(depth, inner.w * 0.5)
            x = inner.x + (inner.w - depth) / 2.0
            rects[spine] = Rect(x, inner.y, depth, inner.h)
            bands = [Rect(inner.x, inner.y, x - inner.x, inner.h),
                     Rect(x + depth, inner.y, inner.x2 - (x + depth), inner.h)]
        rects.update(_fill_bands(others, bands))
    else:
        for r, cell in zip(rooms, squarify([x.target_area_m2 for x in rooms], inner)):
            rects[r.id] = cell

    out = {k: v.snapped() for k, v in rects.items()}
    _assert_sane(out, plan)
    return out


def _fill_bands(rooms: list[RoomSpec], bands: list[Rect]) -> dict[str, Rect]:
    """Distribute rooms across the bands either side of the spine, by area."""
    usable = [b for b in bands if b.w > 0.01 and b.h > 0.01]
    if not usable:
        raise LayoutError("no usable floor area remains beside the circulation spine")

    order = sorted(rooms, key=lambda r: -r.target_area_m2)
    buckets: list[list[RoomSpec]] = [[] for _ in usable]
    load = [0.0] * len(usable)
    caps = [b.area for b in usable]
    for r in order:                       # greedy: fill whichever band is least full
        i = min(range(len(usable)), key=lambda j: load[j] / caps[j] if caps[j] else math.inf)
        buckets[i].append(r)
        load[i] += r.target_area_m2

    out: dict[str, Rect] = {}
    for band, group in zip(usable, buckets):
        if not group:
            continue
        for r, cell in zip(group, squarify([x.target_area_m2 for x in group], band)):
            out[r.id] = cell
    return out


def _assert_sane(rects: dict[str, Rect], plan: ArchitectPlan) -> None:
    for rid, r in rects.items():
        # Tolerance matters: a corridor snapped to exactly 1.20 m can land at
        # 1.19999... in floating point and must not be rejected as too narrow.
        if min(r.w, r.h) < MIN_SIDE - 1e-6:
            raise LayoutError(
                f"room {rid} came out {r.w:.2f} x {r.h:.2f} m; its narrow side is below "
                f"{MIN_SIDE} m. Give it more area, or reduce the number of rooms sharing "
                f"the {plan.envelope.width_m} x {plan.envelope.depth_m} m envelope."
            )
    ids = list(rects)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ra, rb = rects[a], rects[b]
            ox = min(ra.x2, rb.x2) - max(ra.x, rb.x)
            oy = min(ra.y2, rb.y2) - max(ra.y, rb.y)
            if ox > 0.01 and oy > 0.01:
                raise LayoutError(f"rooms {a} and {b} overlap by {ox:.2f} x {oy:.2f} m")


# --------------------------------------------------------------------------
# Rectangles -> walls and openings
# --------------------------------------------------------------------------

@dataclass
class WallSeg:
    name: str
    start: tuple[float, float]
    end: tuple[float, float]
    thickness: float
    external: bool

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)


def shared_edge(a: Rect, b: Rect) -> tuple[str, float, float, float] | None:
    """Return (axis, coord, lo, hi) of the boundary a and b share, if any."""
    tol = 0.02
    if abs(a.x2 - b.x) < tol or abs(b.x2 - a.x) < tol:      # vertical contact
        coord = a.x2 if abs(a.x2 - b.x) < tol else b.x2
        lo, hi = max(a.y, b.y), min(a.y2, b.y2)
        if hi - lo > MIN_DOOR_WALL:
            return ("x", coord, lo, hi)
    if abs(a.y2 - b.y) < tol or abs(b.y2 - a.y) < tol:      # horizontal contact
        coord = a.y2 if abs(a.y2 - b.y) < tol else b.y2
        lo, hi = max(a.x, b.x), min(a.x2, b.x2)
        if hi - lo > MIN_DOOR_WALL:
            return ("y", coord, lo, hi)
    return None


def build_walls(plan: ArchitectPlan, rects: dict[str, Rect]) -> list[WallSeg]:
    """External envelope walls plus one internal partition per shared boundary."""
    e = plan.envelope
    W, D = e.width_m, e.depth_m
    half = e.external_wall_m / 2.0
    walls = [
        WallSeg("EXT-S", (half, half), (W - half, half), e.external_wall_m, True),
        WallSeg("EXT-E", (W - half, half), (W - half, D - half), e.external_wall_m, True),
        WallSeg("EXT-N", (W - half, D - half), (half, D - half), e.external_wall_m, True),
        WallSeg("EXT-W", (half, D - half), (half, half), e.external_wall_m, True),
    ]
    seen: set[tuple] = set()
    ids = sorted(rects)
    n = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            edge = shared_edge(rects[a], rects[b])
            if not edge:
                continue
            axis, coord, lo, hi = edge
            key = (axis, round(coord, 2), round(lo, 2), round(hi, 2))
            if key in seen:
                continue
            seen.add(key)
            n += 1
            if axis == "x":
                seg = WallSeg(f"INT-{n}", (coord, lo), (coord, hi), e.internal_wall_m, False)
            else:
                seg = WallSeg(f"INT-{n}", (lo, coord), (hi, coord), e.internal_wall_m, False)
            walls.append(seg)
    return walls


def _wall_for(walls: list[WallSeg], axis: str, coord: float, lo: float, hi: float) -> WallSeg | None:
    tol = 0.05
    mid = (lo + hi) / 2.0
    for w in walls:
        horizontal = abs(w.start[1] - w.end[1]) < tol
        if axis == "y" and horizontal and abs(w.start[1] - coord) < tol:
            if min(w.start[0], w.end[0]) - tol <= mid <= max(w.start[0], w.end[0]) + tol:
                return w
        if axis == "x" and not horizontal and abs(w.start[0] - coord) < tol:
            if min(w.start[1], w.end[1]) - tol <= mid <= max(w.start[1], w.end[1]) + tol:
                return w
    return None


def _offset_along(wall: WallSeg, point: tuple[float, float]) -> float:
    """Distance from the wall's start to `point`, as the DSL's `at` expects."""
    return math.dist(wall.start, point)


# --------------------------------------------------------------------------
# Source emission
# --------------------------------------------------------------------------

HEADER = '''"""{project} -- generated by recognition.translate. Do not edit by hand.

Regenerate with:  uv run recognition build plans/{slug}.json

Every coordinate below was computed from the ArchitectPlan by deterministic code,
not written by a language model. Change the plan, not this file.
"""
from recognition.design import House

h = House({project!r})
eg = h.storey({storey!r}, elevation=0.0, height={height})
'''


def door_width(tier: str, external: bool) -> float:
    """DIN 18040-2 clear widths when a barrier-free tier is in force."""
    if tier == "din18040_2_R":
        return 0.90
    if tier == "din18040_2":
        return 0.90 if external else 0.80
    return 1.01 if external else 0.885


def emit(plan: ArchitectPlan, rects: dict[str, Rect], walls: list[WallSeg]) -> str:
    """Render the DSL source. Pure string building -- no model, no randomness."""
    slug = plan.project.lower().replace(" ", "-")
    lines = [HEADER.format(project=plan.project, slug=slug,
                           storey=plan.storey_name, height=plan.storey_height_m)]

    lines.append("\n# --- walls: external envelope, then partitions between rooms ---")
    for w in walls:
        lines.append(
            f"eg.wall({w.name!r}, ({snap(w.start[0])}, {snap(w.start[1])}), "
            f"({snap(w.end[0])}, {snap(w.end[1])}), thickness={w.thickness}"
            + (", external=True)" if w.external else ")")
        )

    lines.append("\n# --- rooms: floor outlines inset to the inside face of their walls ---")
    e = plan.envelope
    for r in plan.rooms:
        rect = rects[r.id]
        inset = _inset(rect, plan, e)
        pts = ", ".join(f"({snap(x)}, {snap(y)})" for x, y in inset.polygon())
        lines.append(f"eg.room({r.label!r}, [{pts}])   # {r.id} {rect.area:.1f} m2 target {r.target_area_m2:.1f}")

    tier = plan.accessibility_tier
    lines.append("\n# --- doors: one per adjacency declared in the plan ---")
    lines.extend(_emit_doors(plan, rects, walls, tier))

    lines.append("\n# --- windows: sized to the daylight rule, on exterior walls ---")
    lines.extend(_emit_windows(plan, rects, walls))

    if plan.todo_agent:
        lines.append("\n# --- constructs the translator cannot express ---")
        lines.extend(f"# TODO_AGENT: {t}" for t in plan.todo_agent)

    lines.append(f'\nif __name__ == "__main__":\n    h.write("out/{slug}/model.ifc")\n')
    return "\n".join(lines) + "\n"


def _inset(rect: Rect, plan: ArchitectPlan, e) -> Rect:
    """Pull a room footprint back to the inside face of whatever wall bounds it."""
    def d(on_envelope: bool) -> float:
        return e.external_wall_m / 2.0 if on_envelope else e.internal_wall_m / 2.0
    tol = 0.02
    half = e.external_wall_m / 2.0
    left = d(abs(rect.x - half) < tol)
    right = d(abs(rect.x2 - (e.width_m - half)) < tol)
    bottom = d(abs(rect.y - half) < tol)
    top = d(abs(rect.y2 - (e.depth_m - half)) < tol)
    return Rect(rect.x + left, rect.y + bottom,
                rect.w - left - right, rect.h - bottom - top)


def _nearest_neighbour(room_id: str, rects: dict[str, Rect], exclude: set[str]
                       ) -> tuple[str, tuple | None]:
    """The neighbour sharing the longest usable wall with `room_id`.

    Longest wins because a wider shared boundary is the more natural place to
    hang a door, and because it is a stable, deterministic choice.
    """
    best_id, best_edge, best_len = "", None, 0.0
    for other in rects:
        if other == room_id or other in exclude:
            continue
        edge = shared_edge(rects[other], rects[room_id])
        if edge is None:
            continue
        _axis, _coord, lo, hi = edge
        if hi - lo > best_len:
            best_id, best_edge, best_len = other, edge, hi - lo
    return best_id, best_edge


def _emit_doors(plan, rects, walls, tier) -> list[str]:
    out: list[str] = []
    n = 0
    served: set[str] = set()
    for adj in plan.adjacency:
        if adj.via != "door":
            continue
        edge = shared_edge(rects[adj.a], rects[adj.b])
        partner = adj.a
        if edge is None:
            # The packer does not guarantee that a room touches the one the plan
            # paired it with -- squarify can seat it behind a sibling. Rather
            # than leave the room sealed, open it onto whichever neighbour it
            # actually shares a wall with. The plan's intent (this room is
            # reachable) is honoured even though its literal pairing is not.
            partner, edge = _nearest_neighbour(adj.b, rects, exclude={adj.b})
        if edge is None:
            out.append(f"# TODO_AGENT: room {adj.b} shares no wall long enough for a door "
                       f"with any neighbour; it would be sealed")
            continue
        served.add(adj.b)
        served.add(partner)
        axis, coord, lo, hi = edge
        wall = _wall_for(walls, axis, coord, lo, hi)
        if wall is None:
            out.append(f"# TODO_AGENT: no wall found between {adj.a} and {adj.b}")
            continue
        mid = (coord, (lo + hi) / 2.0) if axis == "x" else ((lo + hi) / 2.0, coord)
        n += 1
        w = door_width(tier, external=False)
        tag = f"D-{n:02d}"
        note = f"{partner} <-> {adj.b}"
        if partner != adj.a:
            note += f"  (plan asked for {adj.a}; rerouted to the neighbour it touches)"
        out.append(
            f"eg.door({tag!r}, on={wall.name!r}, at={snap(_offset_along(wall, mid))}, "
            f"width={w}, height=2.05)   # {note}"
        )
    # An entrance door on the south wall, always -- a house needs a way in.
    ext = next((w for w in walls if w.name == "EXT-S"), None)
    if ext is not None:
        out.append(
            f"eg.door('D-00', on='EXT-S', at={snap(ext.length / 2)}, "
            f"width={door_width(tier, external=True)}, height=2.10, "
            f"external=True, type_name='Eingangstuer')"
        )
    return out


def _emit_windows(plan, rects, walls) -> list[str]:
    """Size each habitable room's glazing to satisfy the daylight ratio.

    The ratio comes from the plan (BayBO Art. 45 (2) = 1/8), never from a model.
    """
    from .contracts import HABITABLE
    out: list[str] = []
    e = plan.envelope
    half = e.external_wall_m / 2.0
    tol = 0.02
    n = 0
    for r in plan.rooms:
        if r.category not in HABITABLE:
            continue
        rect = rects[r.id]
        sides = []
        if abs(rect.y - half) < tol:
            sides.append(("EXT-S", rect.w, (rect.x + rect.x2) / 2, rect.y))
        if abs(rect.y2 - (e.depth_m - half)) < tol:
            sides.append(("EXT-N", rect.w, (rect.x + rect.x2) / 2, rect.y2))
        if abs(rect.x - half) < tol:
            sides.append(("EXT-W", rect.h, rect.x, (rect.y + rect.y2) / 2))
        if abs(rect.x2 - (e.width_m - half)) < tol:
            sides.append(("EXT-E", rect.h, rect.x2, (rect.y + rect.y2) / 2))
        if not sides:
            out.append(f"# TODO_AGENT: room {r.id} ({r.label}) has no exterior wall, "
                       f"so it cannot meet the daylight rule; move it to the perimeter")
            continue
        name, run, cx, cy = max(sides, key=lambda s: s[1])
        wall = next((w for w in walls if w.name == name), None)
        if wall is None:
            continue
        need = rect.area * plan.glazing_ratio          # m2 of opening required
        height = 1.40
        width = min(max(need / height, 0.60), run - 0.60)
        if width <= 0.60:
            height = 1.80
            width = min(max(need / height, 0.60), max(run - 0.60, 0.60))
        n += 1
        tag = f"F-{n:02d}"
        out.append(
            f"eg.window({tag!r}, on={name!r}, at={snap(_offset_along(wall, (cx, cy)))}, "
            f"width={snap(width)}, height={height}, sill=0.90)   "
            f"# {r.id} needs {need:.2f} m2"
        )
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

MAX_FIT_ATTEMPTS = 6
FIT_STEP = 0.06          # grow the envelope 6% per attempt


def fit(plan: ArchitectPlan) -> tuple[ArchitectPlan, dict[str, Rect], int]:
    """Lay the plan out, growing the envelope until every room is habitable.

    Room areas in an ArchitectPlan are *targets*, and the envelope is the
    architect's estimate. When a small room packs into an unusable sliver the
    honest response is a slightly larger building, not a 1.05 m wide utility
    room -- so the envelope grows by a fixed step and the layout is retried.

    Deterministic: same plan in, same envelope out. Returns the adjusted plan,
    the footprints, and how many enlargements it took (0 means it fitted as
    designed), so the run log can report that the building grew.
    """
    import copy
    for attempt in range(MAX_FIT_ATTEMPTS):
        trial = plan if attempt == 0 else copy.deepcopy(plan)
        if attempt:
            grow = (1.0 + FIT_STEP) ** attempt
            trial.envelope.width_m = round(plan.envelope.width_m * grow, 2)
            trial.envelope.depth_m = round(plan.envelope.depth_m * grow, 2)
        try:
            return trial, layout(trial), attempt
        except LayoutError as e:
            last = e
    raise LayoutError(
        f"could not fit the programme after {MAX_FIT_ATTEMPTS} enlargements: {last}"
    )


def translate(plan: ArchitectPlan) -> str:
    """The whole L3 step: validated plan in, DSL source out. No tokens spent."""
    plan.validate()
    fitted, rects, _ = fit(plan)
    walls = build_walls(fitted, rects)
    return emit(fitted, rects, walls)


def translate_to_file(plan: ArchitectPlan, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(translate(plan), encoding="utf-8")
    return p
