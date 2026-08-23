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
MIN_STAIR_AREA = 4.0   # a straight flight plus its landing, at the low end


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

def layout(plan: ArchitectPlan, level: int = 0) -> dict[str, Rect]:
    """Assign every room on one storey an axis-aligned footprint.

    Circulation, if that storey names one, is laid out as a spine strip across
    the interior so every other room has a boundary to open a door onto. The
    spine's position is a pure function of the envelope and the hall's area,
    which is what lets a two-storey building stack: give both storeys a hall of
    the same size and their spines -- and therefore the stair between them --
    land in exactly the same place.
    """
    e = plan.envelope
    half = e.external_wall_m / 2.0
    inner = Rect(half, half, e.width_m - e.external_wall_m, e.depth_m - e.external_wall_m)
    if inner.w <= 0 or inner.h <= 0:
        raise LayoutError(
            f"envelope {e.width_m} x {e.depth_m} m is smaller than its own external walls"
        )

    rooms = [r for r in plan.rooms if r.storey == level]
    if not rooms:
        raise LayoutError(f"storey {level} has no rooms to lay out")
    rects: dict[str, Rect] = {}

    on_level = {r.id for r in rooms}
    spine = plan.circulation_id if plan.circulation_id in on_level else None
    if spine is None:
        spine = next((r.id for r in rooms if r.category == "hall"), None)
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

        # The stair is carved out of one end of the spine rather than packed
        # like a room. Both storeys compute it from the same envelope and the
        # same hall area, so the two flights land exactly above each other --
        # which is what makes the stack buildable instead of decorative.
        stair = next((r for r in rooms if r.category == "stair"), None)
        if stair is not None:
            sp = rects[spine]
            need = max(stair.target_area_m2, MIN_STAIR_AREA)
            if sp.w >= sp.h:
                w = min(max(need / sp.h, MIN_SIDE), sp.w * 0.45)
                rects[stair.id] = Rect(sp.x2 - w, sp.y, w, sp.h)
                rects[spine] = Rect(sp.x, sp.y, sp.w - w, sp.h)
            else:
                hh = min(max(need / sp.w, MIN_SIDE), sp.h * 0.45)
                rects[stair.id] = Rect(sp.x, sp.y2 - hh, sp.w, hh)
                rects[spine] = Rect(sp.x, sp.y, sp.w, sp.h - hh)
            others = [r for r in others if r.id != stair.id]

        rects.update(_fill_bands(others, bands))
    else:
        for r, cell in zip(rooms, squarify([x.target_area_m2 for x in rooms], inner)):
            rects[r.id] = cell

    out = {k: v.snapped() for k, v in rects.items()}
    _assert_sane(out, plan)
    return out


def layout_all(plan: ArchitectPlan) -> list[dict[str, Rect]]:
    """One footprint map per storey, ground floor first."""
    return [layout(plan, level) for level in range(plan.storey_count)]


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
'''

STOREY_NAMES = ("Erdgeschoss", "Obergeschoss")
STOREY_VARS = ("eg", "og")

# A window wider than this stops reading as a window and starts reading as a
# curtain wall. Rooms that need more glazing get several windows instead of one
# enormous one -- which is what a person would draw.
MAX_WINDOW_W = 2.40
MIN_WINDOW_W = 0.70
WINDOW_GAP = 0.60


def door_width(tier: str, external: bool) -> float:
    """DIN 18040-2 clear widths when a barrier-free tier is in force."""
    if tier == "din18040_2_R":
        return 0.90
    if tier == "din18040_2":
        return 0.90 if external else 0.80
    return 1.01 if external else 0.885


def emit(plan: ArchitectPlan, rects_by_level: list[dict[str, Rect]],
         walls_by_level: list[list[WallSeg]]) -> str:
    """Render the DSL source. Pure string building -- no model, no randomness."""
    slug = plan.project.lower().replace(" ", "-")
    lines = [HEADER.format(project=plan.project, slug=slug)]
    e = plan.envelope
    tier = plan.accessibility_tier

    for level in range(plan.storey_count):
        var = STOREY_VARS[level]
        name = STOREY_NAMES[level] if level < len(STOREY_NAMES) else f"Geschoss {level}"
        rects = rects_by_level[level]
        walls = walls_by_level[level]
        rooms = [r for r in plan.rooms if r.storey == level]
        elevation = round(level * plan.storey_height_m, 3)

        lines.append(f"\n# ═══ {name} ═══")
        lines.append(
            f"{var} = h.storey({name!r}, elevation={elevation}, height={plan.storey_height_m})"
        )

        lines.append(f"\n# --- {name}: walls ---")
        for w in walls:
            lines.append(
                f"{var}.wall({w.name!r}, ({snap(w.start[0])}, {snap(w.start[1])}), "
                f"({snap(w.end[0])}, {snap(w.end[1])}), thickness={w.thickness}"
                + (", external=True)" if w.external else ")")
            )

        lines.append(f"\n# --- {name}: rooms, inset to the inside face of their walls ---")
        for r in rooms:
            rect = rects[r.id]
            inset = _inset(rect, plan, e)
            pts = ", ".join(f"({snap(x)}, {snap(y)})" for x, y in inset.polygon())
            lines.append(
                f"{var}.room({r.label!r}, [{pts}])   # {r.id} {rect.area:.1f} m2 "
                f"target {r.target_area_m2:.1f}"
            )

        # One ledger of occupied wall runs per storey: doors claim first (the
        # entrance above all), windows route around whatever is taken.
        occupied: dict[str, list[tuple[float, float]]] = {}
        lines.append(f"\n# --- {name}: doors ---")
        lines.extend(_emit_doors(plan, rects, walls, tier, occupied, level, var))

        lines.append(f"\n# --- {name}: windows, sized to the daylight rule ---")
        lines.extend(_emit_windows(plan, rects, walls, occupied, level, var))

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


def neighbours(rects: dict[str, Rect]) -> dict[str, dict[str, tuple]]:
    """Which rooms share a wall long enough to hold a door, and where."""
    out: dict[str, dict[str, tuple]] = {rid: {} for rid in rects}
    ids = sorted(rects)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            edge = shared_edge(rects[a], rects[b])
            if edge:
                out[a][b] = edge
                out[b][a] = edge
    return out


def _place(occupied: dict[str, list[tuple[float, float]]], wall_name: str,
           seg_lo: float, seg_hi: float, center: float, width: float, *,
           clearance: float = 0.10, margin: float = 0.15,
           min_width: float = 0.60, allow_shrink: bool = True
           ) -> tuple[float, float] | None:
    """Find a clear run for an opening on a wall, or None if there is none.

    Openings must never overlap -- a door punched through a window is the kind
    of geometry a model can emit and a person would never draw, and exactly
    what this deterministic layer exists to prevent.
    """
    lo, hi = min(seg_lo, seg_hi) + margin, max(seg_lo, seg_hi) - margin
    if hi - lo < min_width:
        return None
    width = min(width, hi - lo)
    taken = sorted(occupied.get(wall_name, []))

    gaps: list[tuple[float, float]] = []
    cursor = lo
    for t_lo, t_hi in taken:
        t_lo, t_hi = t_lo - clearance, t_hi + clearance
        if t_hi <= lo or t_lo >= hi:
            continue
        if t_lo > cursor:
            gaps.append((cursor, min(t_lo, hi)))
        cursor = max(cursor, t_hi)
    if cursor < hi:
        gaps.append((cursor, hi))

    best: tuple[float, float, float] | None = None       # (score, at, width)
    for g_lo, g_hi in gaps:
        if g_hi - g_lo >= width:
            at = min(max(center, g_lo + width / 2), g_hi - width / 2)
            score = abs(at - center)
            if best is None or score < best[0]:
                best = (score, at, width)
    if best is None and allow_shrink and gaps:
        g_lo, g_hi = max(gaps, key=lambda g: g[1] - g[0])
        if g_hi - g_lo >= min_width:
            best = (0.0, (g_lo + g_hi) / 2, g_hi - g_lo)
    if best is None:
        return None
    _score, at, width = best
    occupied.setdefault(wall_name, []).append((at - width / 2, at + width / 2))
    return at, width


def _door_line(var, tag, wall, at, width, note):
    return (f"{var}.door({tag!r}, on={wall.name!r}, at={snap(at)}, "
            f"width={width}, height=2.05)   # {note}")


def _emit_doors(plan, rects, walls, tier,
                occupied: dict[str, list[tuple[float, float]]],
                level: int, var: str) -> list[str]:
    """Doors for one storey, then a reachability repair pass.

    The plan declares which rooms should connect, but the packer does not
    guarantee those rooms actually touch. Emitting only the declared doors is
    how a room ends up reachable solely through another room -- or not at all.
    So after the declared doors are placed, the door graph is walked from the
    way in, and anything stranded gets a door onto a room that is already
    reachable. A building where you cannot get to a room is not a building.
    """
    out: list[str] = []
    nb = neighbours(rects)
    linked: dict[str, set[str]] = {rid: set() for rid in rects}
    n = 0

    def place_between(a: str, b: str, tag_no: int) -> bool:
        edge = nb.get(a, {}).get(b)
        if not edge:
            return False
        axis, coord, lo, hi = edge
        wall = _wall_for(walls, axis, coord, lo, hi)
        if wall is None:
            return False
        p_lo = (coord, lo) if axis == "x" else (lo, coord)
        p_hi = (coord, hi) if axis == "x" else (hi, coord)
        seg_lo, seg_hi = _offset_along(wall, p_lo), _offset_along(wall, p_hi)
        w = door_width(tier, external=False)
        spot = _place(occupied, wall.name, seg_lo, seg_hi,
                      (seg_lo + seg_hi) / 2, w, allow_shrink=False)
        if spot is None:
            return False
        at, _w = spot
        out.append(_door_line(var, f"D-{level}{tag_no:02d}", wall, at, w, f"{a} <-> {b}"))
        linked[a].add(b)
        linked[b].add(a)
        return True

    # The way in: an entrance on the south wall of the ground floor. It is
    # placed first so every later opening on that wall routes around it.
    entry_room = None
    if level == 0:
        ext = next((w for w in walls if w.name == "EXT-S"), None)
        if ext is not None:
            w_ext = door_width(tier, external=True)
            spot = _place(occupied, "EXT-S", 0.0, ext.length, ext.length / 2, w_ext,
                          allow_shrink=False)
            if spot is not None:
                at, _w = spot
                out.append(
                    f"{var}.door('D-000', on='EXT-S', at={snap(at)}, "
                    f"width={w_ext}, height=2.10, "
                    f"external=True, type_name='Eingangstuer')"
                )
                # whichever room the entrance actually opens into
                half = plan.envelope.external_wall_m / 2.0
                entry_room = next(
                    (rid for rid, r in rects.items()
                     if abs(r.y - half) < 0.05 and r.x - 0.05 <= at <= r.x2 + 0.05),
                    None,
                )
    if entry_room is None:
        # upper storeys start at the stair; a hall is the next best root
        entry_room = next((r.id for r in plan.rooms
                           if r.storey == level and r.category == "stair"), None)
        if entry_room is None:
            entry_room = next((r.id for r in plan.rooms
                               if r.storey == level and r.category == "hall"), None)
    if entry_room is None and rects:
        entry_room = sorted(rects)[0]

    # 1 · the doors the plan asked for
    for adj in plan.adjacency:
        if adj.via != "door":
            continue
        if adj.a not in rects or adj.b not in rects:
            continue          # a pairing across storeys; the stair carries that
        if adj.b in linked[adj.a]:
            continue
        n += 1
        if not place_between(adj.a, adj.b, n):
            n -= 1

    # 2 · reachability repair — everything must be reachable from the way in
    reachable = set()
    stack = [entry_room] if entry_room else []
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack.extend(linked[cur] - reachable)

    stranded = [r for r in sorted(rects) if r not in reachable]
    for rid in stranded:
        # prefer a door onto circulation, then onto any already-reachable room
        options = sorted(
            (o for o in nb[rid] if o in reachable),
            key=lambda o: (0 if _category(plan, o) in ("hall", "stair") else 1,
                           -(nb[rid][o][3] - nb[rid][o][2])),
        )
        placed = False
        for other in options:
            n += 1
            if place_between(rid, other, n):
                out.append(f"# reachability: {rid} had no way in; opened onto {other}")
                placed = True
                reachable.add(rid)
                stack = [rid]
                while stack:
                    cur = stack.pop()
                    for nxt in linked[cur] - reachable:
                        reachable.add(nxt)
                        stack.append(nxt)
                break
            n -= 1
        if not placed:
            out.append(f"# TODO_AGENT: room {rid} shares no wall long enough for a door "
                       f"with any reachable room; it would be sealed")
    return out


def _category(plan, room_id: str) -> str:
    for r in plan.rooms:
        if r.id == room_id:
            return r.category
    return "other"


def _emit_windows(plan, rects, walls,
                  occupied: dict[str, list[tuple[float, float]]],
                  level: int, var: str) -> list[str]:
    """Glazing for one storey, sized to the daylight ratio and split sensibly.

    The ratio comes from the plan (BayBO Art. 45 (2) = 1/8), never from a
    model. A room needing more glass than one sane window can carry gets
    several evenly spaced windows rather than one twenty-metre slot.
    """
    from .contracts import HABITABLE
    out: list[str] = []
    e = plan.envelope
    half = e.external_wall_m / 2.0
    tol = 0.02
    n = 0
    for r in plan.rooms:
        if r.storey != level or r.category not in HABITABLE:
            continue
        rect = rects[r.id]
        sides = []
        if abs(rect.y - half) < tol:
            sides.append(("EXT-S", rect.w, (rect.x, rect.y), (rect.x2, rect.y)))
        if abs(rect.y2 - (e.depth_m - half)) < tol:
            sides.append(("EXT-N", rect.w, (rect.x, rect.y2), (rect.x2, rect.y2)))
        if abs(rect.x - half) < tol:
            sides.append(("EXT-W", rect.h, (rect.x, rect.y), (rect.x, rect.y2)))
        if abs(rect.x2 - (e.width_m - half)) < tol:
            sides.append(("EXT-E", rect.h, (rect.x2, rect.y), (rect.x2, rect.y2)))
        if not sides:
            out.append(f"# TODO_AGENT: room {r.id} ({r.label}) has no exterior wall, "
                       f"so it cannot meet the daylight rule; move it to the perimeter")
            continue

        need = rect.area * plan.glazing_ratio          # m2 of opening required
        sill = 0.90
        h_max = max(0.80, plan.storey_height_m - sill - 0.05)
        height = min(1.40, h_max)
        got = 0.0
        # widest wall first, then the next one if the first cannot carry it all
        for name, run, p_a, p_b in sorted(sides, key=lambda s: -s[1]):
            if got >= need - 1e-6:
                break
            wall = next((w for w in walls if w.name == name), None)
            if wall is None:
                continue
            seg_lo, seg_hi = _offset_along(wall, p_a), _offset_along(wall, p_b)
            lo, hi = min(seg_lo, seg_hi), max(seg_lo, seg_hi)
            span = hi - lo
            remaining = need - got
            # how many windows this wall should carry, at a width a person
            # would actually draw
            count = max(1, math.ceil(remaining / (MAX_WINDOW_W * height)))
            count = min(count, max(1, int((span - WINDOW_GAP) // (MIN_WINDOW_W + WINDOW_GAP))))
            width = max(MIN_WINDOW_W, min(MAX_WINDOW_W, remaining / (count * height)))
            slot = span / count
            for k in range(count):
                if got >= need - 1e-6:
                    break
                centre = lo + slot * (k + 0.5)
                spot = _place(occupied, name, lo, hi, centre, width, margin=0.30)
                if spot is None:
                    continue
                at, got_w = spot
                if got_w < MIN_WINDOW_W - 1e-6:
                    continue
                n += 1
                got += got_w * height
                out.append(
                    f"{var}.window({f'F-{level}{n:02d}'!r}, on={name!r}, at={snap(at)}, "
                    f"width={snap(got_w)}, height={height}, sill={sill})   "
                    f"# {r.id} needs {need:.2f} m2"
                )
        if got <= 0:
            out.append(f"# TODO_AGENT: no clear exterior run for a window in {r.id} "
                       f"({r.label}); every reachable wall is fully occupied")
        elif got < need - 1e-6:
            out.append(f"#   {r.id}: {got:.2f} m2 of {need:.2f} m2 placed — the verifier "
                       f"will report the shortfall rather than hide it")
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

MAX_FIT_ATTEMPTS = 6
FIT_STEP = 0.06          # grow the envelope 6% per attempt


def fit(plan: ArchitectPlan) -> tuple[ArchitectPlan, list[dict[str, Rect]], int]:
    """Lay every storey out, growing the envelope until the rooms are habitable.

    Room areas are targets and the envelope is an estimate. When a small room
    packs into an unusable sliver the honest response is a slightly larger
    building, not a 1.05 m wide utility room -- so the envelope grows by a
    fixed step and the layout is retried. Deterministic: same plan in, same
    envelope out.
    """
    import copy
    last: Exception | None = None
    for attempt in range(MAX_FIT_ATTEMPTS):
        trial = plan if attempt == 0 else copy.deepcopy(plan)
        if attempt:
            grow = (1.0 + FIT_STEP) ** attempt
            trial.envelope.width_m = round(plan.envelope.width_m * grow, 2)
            trial.envelope.depth_m = round(plan.envelope.depth_m * grow, 2)
        try:
            return trial, layout_all(trial), attempt
        except LayoutError as e:
            last = e
    raise LayoutError(
        f"could not fit the programme after {MAX_FIT_ATTEMPTS} enlargements: {last}"
    )


def translate(plan: ArchitectPlan) -> str:
    """The whole L3 step: validated plan in, DSL source out. No tokens spent."""
    plan.validate()
    fitted, rects_by_level, _ = fit(plan)
    walls_by_level = [build_walls(fitted, rects) for rects in rects_by_level]
    return emit(fitted, rects_by_level, walls_by_level)


def translate_to_file(plan: ArchitectPlan, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(translate(plan), encoding="utf-8")
    return p
