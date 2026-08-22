"""2D drawing generation: dimensioned floor plans on titled sheets.

Outputs per storey: SVG (source of truth, diffable), PDF/PNG (for humans and
PRs) and DXF (opens in AutoCAD / Revit / ArchiCAD). SVG and DXF share the same
symbol geometry (door swings, window lines, dimension chains) computed here,
so the two never disagree.

Drawing conventions live in SHEET / STYLE below. Devin: change conventions
here, never by post-editing generated files.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import cairosvg
import ezdxf
import svgwrite
from shapely import minimum_rotated_rectangle
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from .model import Model, Opening, Storey

# --- conventions -----------------------------------------------------------

SHEET = {
    "size_mm": (420.0, 297.0),  # A3 landscape
    "margin_mm": 10.0,
    "title_block_h_mm": 38.0,
    "scales": (50, 100, 200, 500),  # candidate scales, first that fits wins
    "dim_offsets_m": (1.2, 2.4),  # distance of opening chain / overall dim from the building
}
STYLE = {
    "wall_fill": "#2b2b2b", "space_fill": "#eef3fb", "space_stroke": "#9fb3d9",
    "door": "#b5651d", "window": "#2a7fff", "dim": "#555555", "text": "#111111",
    "font": "Helvetica, Arial, sans-serif",
}


@dataclass
class DoorSymbol:
    opening: tuple[tuple[float, float], tuple[float, float]]  # jamb-to-jamb line (m, world)
    leaf: tuple[tuple[float, float], tuple[float, float]]  # hinge -> leaf tip
    arc_center: tuple[float, float]
    arc_radius: float
    arc_start_deg: float  # CCW from +x, ezdxf convention
    arc_end_deg: float
    arc_points: list[tuple[float, float]]  # sampled polyline for SVG


@dataclass
class WindowSymbol:
    lines: list[tuple[tuple[float, float], tuple[float, float]]]


@dataclass
class DimChain:
    axis: str  # "x" or "y"
    offset: float  # world coordinate of the dimension line (y for x-axis chains, x for y-axis chains)
    stations: list[float]  # sorted world coordinates along the axis


# --- symbol geometry (shared by SVG and DXF) --------------------------------

def _long_axis(g) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Return (p0, p1, short_side) where p0->p1 is the centreline along the long axis."""
    rect = minimum_rotated_rectangle(g)
    c = list(rect.exterior.coords)[:4]
    d01 = Point(c[0]).distance(Point(c[1]))
    d12 = Point(c[1]).distance(Point(c[2]))
    if d01 >= d12:
        p0 = ((c[0][0] + c[3][0]) / 2, (c[0][1] + c[3][1]) / 2)
        p1 = ((c[1][0] + c[2][0]) / 2, (c[1][1] + c[2][1]) / 2)
        short = d12
    else:
        p0 = ((c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2)
        p1 = ((c[2][0] + c[3][0]) / 2, (c[2][1] + c[3][1]) / 2)
        short = d01
    return p0, p1, short


def door_symbol(model: Model, d: Opening) -> DoorSymbol:
    p0, p1, short = _long_axis(d.footprint)
    ux, uy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(ux, uy) or 1.0
    ux, uy = ux / L, uy / L
    nx, ny = -uy, ux  # left normal
    # swing into the side that has a room (fallback: +normal)
    mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    probe_d = max(short, 0.3) + 0.4
    side = 1.0
    spaces = model.spaces_on(d.storey)
    for sgn in (1.0, -1.0):
        pt = Point(mid[0] + nx * sgn * probe_d, mid[1] + ny * sgn * probe_d)
        if any(s.footprint.contains(pt) for s in spaces):
            side = sgn
            break
    w = d.width if d.width else L
    hinge = p0
    tip = (hinge[0] + nx * side * w, hinge[1] + ny * side * w)
    a_jamb = math.degrees(math.atan2(uy, ux))
    a_tip = math.degrees(math.atan2(ny * side, nx * side))
    # ezdxf arcs run CCW from start to end
    if side > 0:
        a_start, a_end = a_jamb, a_tip
    else:
        a_start, a_end = a_tip, a_jamb
    pts = []
    for i in range(13):
        t = i / 12
        ang = math.radians(a_start + t * ((a_end - a_start) % 360))
        pts.append((hinge[0] + w * math.cos(ang), hinge[1] + w * math.sin(ang)))
    return DoorSymbol((p0, p1), (hinge, tip), hinge, w, a_start, a_end, pts)


def window_symbol(w: Opening) -> WindowSymbol:
    p0, p1, short = _long_axis(w.footprint)
    ux, uy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(ux, uy) or 1.0
    nx, ny = -uy / L, ux / L
    off = min(short / 4, 0.06)
    lines = []
    for k in (-1, 1):
        lines.append(((p0[0] + nx * k * off, p0[1] + ny * k * off), (p1[0] + nx * k * off, p1[1] + ny * k * off)))
    return WindowSymbol(lines)


def _snap(v: float, step: float = 0.01) -> float:
    return round(round(v / step) * step, 3)


def dimension_chains(model: Model, storey: str) -> list[DimChain]:
    """Exterior dimension chains: wall-face + opening stations along x (below) and y (left)."""
    walls = model.walls_on(storey)
    ext = [w for w in walls if w.is_external] or walls
    minx, miny, maxx, maxy = _union_bounds([w.footprint for w in walls])
    o1, o2 = SHEET["dim_offsets_m"]

    def stations(axis: str, outer_lo: float, outer_hi: float) -> list[float]:
        pts: set[float] = set()
        # outer faces of exterior walls + jambs of exterior openings on them
        for w in ext:
            b = w.bounds
            lo, hi = (b[0], b[2]) if axis == "x" else (b[1], b[3])
            # keep only walls that run along the axis (long in that direction)
            if (hi - lo) > w.thickness * 1.5:
                pts.update((_snap(lo), _snap(hi)))
        for op in model.doors_on(storey) + model.windows_on(storey):
            if op.is_external is False:
                continue
            b = op.bounds
            lo, hi = (b[0], b[2]) if axis == "x" else (b[1], b[3])
            if (hi - lo) >= op.width * 0.8:  # opening runs along this axis
                pts.update((_snap(lo), _snap(hi)))
        pts.update((_snap(outer_lo), _snap(outer_hi)))
        st = sorted(pts)
        # drop stations closer than 5 cm to their predecessor (keeps chains legible)
        cleaned = [st[0]]
        for v in st[1:]:
            if v - cleaned[-1] > 0.05:
                cleaned.append(v)
        return cleaned

    return [
        DimChain("x", miny - o1, stations("x", minx, maxx)),
        DimChain("x", miny - o2, [_snap(minx), _snap(maxx)]),
        DimChain("y", minx - o1, stations("y", miny, maxy)),
        DimChain("y", minx - o2, [_snap(miny), _snap(maxy)]),
    ]


def _union_bounds(geoms) -> tuple[float, float, float, float]:
    bs = [g.bounds for g in geoms if not g.is_empty]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


# --- SVG sheet -------------------------------------------------------------

class _Sheet:
    """Maps world metres to sheet millimetres for a chosen scale, origin top-left."""

    def __init__(self, world_bounds, scale: int):
        W, H = SHEET["size_mm"]
        m = SHEET["margin_mm"]
        self.k = 1000.0 / scale  # mm per metre
        minx, miny, maxx, maxy = world_bounds
        dw, dh = (maxx - minx) * self.k, (maxy - miny) * self.k
        avail_w, avail_h = W - 2 * m, H - 2 * m - SHEET["title_block_h_mm"]
        self.ox = m + (avail_w - dw) / 2 - minx * self.k
        self.oy = m + (avail_h - dh) / 2 + maxy * self.k
        self.fits = dw <= avail_w and dh <= avail_h
        self.scale = scale

    def p(self, xy) -> tuple[float, float]:
        return (self.ox + xy[0] * self.k, self.oy - xy[1] * self.k)


def _choose_scale(world_bounds) -> _Sheet:
    for s in SHEET["scales"]:
        sh = _Sheet(world_bounds, s)
        if sh.fits:
            return sh
    return sh  # largest scale even if it does not fit


def _plan_bounds(model: Model, storey: str):
    geoms = [w.footprint for w in model.walls_on(storey)] + [s.footprint for s in model.spaces_on(storey)]
    minx, miny, maxx, maxy = _union_bounds(geoms)
    pad = SHEET["dim_offsets_m"][1] + 1.0
    return (minx - pad, miny - pad, maxx + 0.5, maxy + 0.5)


def _fmt_mm(v_m: float) -> str:
    mm = int(round(v_m * 1000))
    return f"{mm:,}".replace(",", " ")


def plan_svg(model: Model, storey: Storey, out_svg: Path, *, project: str = "", sheet_no: str = "A-101",
             revision: str = "", scale: int | None = None) -> Path:
    st = storey.name
    sh = _Sheet(_plan_bounds(model, st), scale) if scale else _choose_scale(_plan_bounds(model, st))
    W, H = SHEET["size_mm"]
    dwg = svgwrite.Drawing(str(out_svg), size=(f"{W}mm", f"{H}mm"), viewBox=f"0 0 {W} {H}")
    dwg.add(dwg.rect((0, 0), (W, H), fill="white"))
    P = sh.p

    def poly(g, **kw):
        for part in (g.geoms if isinstance(g, MultiPolygon) else [g]):
            path = dwg.path(d=_ring_path(part.exterior.coords, P), **kw)
            for hole in part.interiors:
                path.push(_ring_path(hole.coords, P))
            path.update({"fill-rule": "evenodd"})
            dwg.add(path)

    # rooms
    for s in model.spaces_on(st):
        poly(s.footprint, fill=STYLE["space_fill"], stroke=STYLE["space_stroke"], stroke_width=0.15)
    # walls
    for w in model.walls_on(st):
        poly(w.footprint, fill=STYLE["wall_fill"], stroke="none")
    # openings cut out of walls
    for op in model.doors_on(st) + model.windows_on(st):
        poly(op.footprint, fill="white", stroke="none")
    # windows (tag placed outside the building, along the window's outward normal)
    bminx, bminy, bmaxx, bmaxy = _union_bounds([w.footprint for w in model.walls_on(st)])
    bc = ((bminx + bmaxx) / 2, (bminy + bmaxy) / 2)
    for w in model.windows_on(st):
        for a, b in window_symbol(w).lines:
            dwg.add(dwg.line(P(a), P(b), stroke=STYLE["window"], stroke_width=0.35))
        c = P((w.centroid.x, w.centroid.y))
        dx, dy = w.centroid.x - bc[0], w.centroid.y - bc[1]
        if abs(dx) > abs(dy):
            anchor, pos = ("start" if dx > 0 else "end"), (c[0] + (2.0 if dx > 0 else -2.0), c[1] + 0.7)
        else:
            anchor, pos = "middle", (c[0], c[1] + (-1.6 if dy > 0 else 2.6))
        dwg.add(dwg.text(w.tag, insert=pos, font_size=1.8, fill=STYLE["window"],
                         text_anchor=anchor, font_family=STYLE["font"]))
    # doors
    for d in model.doors_on(st):
        sym = door_symbol(model, d)
        dwg.add(dwg.line(P(sym.leaf[0]), P(sym.leaf[1]), stroke=STYLE["door"], stroke_width=0.4))
        dwg.add(dwg.polyline([P(q) for q in sym.arc_points], fill="none", stroke=STYLE["door"],
                             stroke_width=0.2, stroke_dasharray="0.8,0.5"))
        c = P(sym.leaf[1])
        dwg.add(dwg.text(d.tag, insert=(c[0], c[1] - 0.8), font_size=1.8, fill=STYLE["door"],
                         text_anchor="middle", font_family=STYLE["font"]))
    # room labels
    for s in model.spaces_on(st):
        c = P((s.centroid.x, s.centroid.y))
        dwg.add(dwg.text(f"{s.tag}  {s.label}", insert=(c[0], c[1] - 1.0), font_size=2.6, fill=STYLE["text"],
                         text_anchor="middle", font_family=STYLE["font"], font_weight="bold"))
        dwg.add(dwg.text(f"{s.area:.1f} m²", insert=(c[0], c[1] + 2.2), font_size=2.2, fill=STYLE["text"],
                         text_anchor="middle", font_family=STYLE["font"]))
    # dimension chains
    for chain in dimension_chains(model, st):
        _svg_dim_chain(dwg, sh, chain)
    # north arrow + scale bar
    _svg_north(dwg, (W - SHEET["margin_mm"] - 12, SHEET["margin_mm"] + 14))
    _svg_scale_bar(dwg, sh, (SHEET["margin_mm"] + 5, H - SHEET["margin_mm"] - SHEET["title_block_h_mm"] - 6))
    # title block + border
    _svg_title_block(dwg, project=project or model.path.stem, title=f"FLOOR PLAN — {st.upper()}",
                     sheet_no=sheet_no, scale=sh.scale, revision=revision, model=model.path.name)
    m = SHEET["margin_mm"]
    dwg.add(dwg.rect((m, m), (W - 2 * m, H - 2 * m), fill="none", stroke="#000", stroke_width=0.5))
    dwg.save()
    return out_svg


def _ring_path(coords, P) -> str:
    pts = [P(c) for c in coords]
    return "M " + " L ".join(f"{x:.3f},{y:.3f}" for x, y in pts) + " Z"


def _svg_dim_chain(dwg, sh: _Sheet, chain: DimChain) -> None:
    col, tick = STYLE["dim"], 1.0
    st = chain.stations
    if len(st) < 2:
        return
    if chain.axis == "x":
        a, b = sh.p((st[0], chain.offset)), sh.p((st[-1], chain.offset))
        dwg.add(dwg.line(a, b, stroke=col, stroke_width=0.18))
        for v in st:
            x, y = sh.p((v, chain.offset))
            dwg.add(dwg.line((x - tick * 0.5, y + tick * 0.5), (x + tick * 0.5, y - tick * 0.5), stroke=col, stroke_width=0.25))
        for u, v in zip(st, st[1:]):
            x, y = sh.p(((u + v) / 2, chain.offset))
            dwg.add(dwg.text(_fmt_mm(v - u), insert=(x, y - 0.8), font_size=1.9, fill=col,
                             text_anchor="middle", font_family=STYLE["font"]))
    else:
        a, b = sh.p((chain.offset, st[0])), sh.p((chain.offset, st[-1]))
        dwg.add(dwg.line(a, b, stroke=col, stroke_width=0.18))
        for v in st:
            x, y = sh.p((chain.offset, v))
            dwg.add(dwg.line((x - tick * 0.5, y + tick * 0.5), (x + tick * 0.5, y - tick * 0.5), stroke=col, stroke_width=0.25))
        for u, v in zip(st, st[1:]):
            x, y = sh.p((chain.offset, (u + v) / 2))
            t = dwg.text(_fmt_mm(v - u), insert=(x - 0.8, y), font_size=1.9, fill=col,
                         text_anchor="middle", font_family=STYLE["font"])
            t.rotate(-90, center=(x - 0.8, y))
            dwg.add(t)


def _svg_north(dwg, at) -> None:
    x, y = at
    dwg.add(dwg.polygon([(x, y - 8), (x - 3, y + 2), (x, y), (x + 3, y + 2)], fill="#000"))
    dwg.add(dwg.text("N", insert=(x, y - 9.5), font_size=3, text_anchor="middle", font_family=STYLE["font"], font_weight="bold"))


def _svg_scale_bar(dwg, sh: _Sheet, at) -> None:
    x, y = at
    seg = sh.k  # 1 m in mm
    for i in range(5):
        dwg.add(dwg.rect((x + i * seg, y), (seg, 1.2), fill="#000" if i % 2 == 0 else "#fff", stroke="#000", stroke_width=0.2))
        dwg.add(dwg.text(str(i), insert=(x + i * seg, y - 0.8), font_size=1.8, text_anchor="middle", font_family=STYLE["font"]))
    dwg.add(dwg.text("5 m", insert=(x + 5 * seg, y - 0.8), font_size=1.8, text_anchor="middle", font_family=STYLE["font"]))


def _svg_title_block(dwg, *, project, title, sheet_no, scale, revision, model) -> None:
    W, H = SHEET["size_mm"]
    m, h = SHEET["margin_mm"], SHEET["title_block_h_mm"]
    x0, y0, w = W - m - 150, H - m - h, 150
    dwg.add(dwg.rect((x0, y0), (w, h), fill="white", stroke="#000", stroke_width=0.5))
    dwg.add(dwg.line((x0, y0 + 12), (x0 + w, y0 + 12), stroke="#000", stroke_width=0.3))
    dwg.add(dwg.line((x0 + 95, y0 + 12), (x0 + 95, y0 + h), stroke="#000", stroke_width=0.3))
    f = STYLE["font"]
    dwg.add(dwg.text(project, insert=(x0 + 3, y0 + 8), font_size=5, font_family=f, font_weight="bold"))
    dwg.add(dwg.text(title, insert=(x0 + 3, y0 + 20), font_size=4, font_family=f))
    dwg.add(dwg.text(f"Model: {model}", insert=(x0 + 3, y0 + 27), font_size=2.4, font_family=f, fill="#444"))
    dwg.add(dwg.text("Generated by Recognition — do not edit by hand; change the generator.",
                     insert=(x0 + 3, y0 + 33), font_size=2.2, font_family=f, fill="#666"))
    dwg.add(dwg.text("SHEET", insert=(x0 + 98, y0 + 16), font_size=2.2, font_family=f, fill="#666"))
    dwg.add(dwg.text(sheet_no, insert=(x0 + 98, y0 + 24), font_size=6, font_family=f, font_weight="bold"))
    dwg.add(dwg.text(f"SCALE 1:{scale}  ·  A3", insert=(x0 + 98, y0 + 30), font_size=2.4, font_family=f))
    dwg.add(dwg.text(f"{date.today().isoformat()}  ·  REV {revision or '-'}", insert=(x0 + 98, y0 + 35), font_size=2.4, font_family=f))


def svg_to_pdf(svg: Path, pdf: Path) -> Path:
    cairosvg.svg2pdf(url=str(svg), write_to=str(pdf))
    return pdf


def svg_to_png(svg: Path, png: Path, dpi: int = 150) -> Path:
    cairosvg.svg2png(url=str(svg), write_to=str(png), dpi=dpi, background_color="white")
    return png


# --- DXF -------------------------------------------------------------------

LAYERS = {
    "A-WALL": 7, "A-AREA": 8, "A-AREA-IDEN": 2, "A-DOOR": 30, "A-GLAZ": 5, "A-ANNO-DIMS": 1, "A-ANNO-TEXT": 3,
}


def plan_dxf(model: Model, storey: Storey, out_dxf: Path) -> Path:
    """DXF in millimetres, world coordinates, AIA-style layer names."""
    st = storey.name
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # mm
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    K = 1000.0

    def mm(p):
        return (p[0] * K, p[1] * K)

    def add_poly(g, layer):
        for part in (g.geoms if isinstance(g, MultiPolygon) else [g]):
            msp.add_lwpolyline([mm(c) for c in part.exterior.coords], close=True, dxfattribs={"layer": layer})
            for hole in part.interiors:
                msp.add_lwpolyline([mm(c) for c in hole.coords], close=True, dxfattribs={"layer": layer})

    for w in model.walls_on(st):
        add_poly(w.footprint, "A-WALL")
    for s in model.spaces_on(st):
        add_poly(s.footprint, "A-AREA")
        c = mm((s.centroid.x, s.centroid.y))
        msp.add_mtext(f"{s.tag} {s.label}\\P{s.area:.1f} m²", dxfattribs={"layer": "A-AREA-IDEN", "char_height": 200}) \
            .set_location(c, attachment_point=5)
    for w in model.windows_on(st):
        for a, b in window_symbol(w).lines:
            msp.add_line(mm(a), mm(b), dxfattribs={"layer": "A-GLAZ"})
    for d in model.doors_on(st):
        sym = door_symbol(model, d)
        msp.add_line(mm(sym.leaf[0]), mm(sym.leaf[1]), dxfattribs={"layer": "A-DOOR"})
        msp.add_arc(mm(sym.arc_center), sym.arc_radius * K, sym.arc_start_deg, sym.arc_end_deg, dxfattribs={"layer": "A-DOOR"})
        msp.add_text(d.tag, dxfattribs={"layer": "A-ANNO-TEXT", "height": 150}).set_placement(mm(sym.leaf[1]))
    for chain in dimension_chains(model, st):
        for u, v in zip(chain.stations, chain.stations[1:]):
            if chain.axis == "x":
                p1, p2, base = (u, chain.offset + 0.3), (v, chain.offset + 0.3), (u, chain.offset)
            else:
                p1, p2, base = (chain.offset + 0.3, u), (chain.offset + 0.3, v), (chain.offset, u)
            dim = msp.add_linear_dim(base=mm(base), p1=mm(p1), p2=mm(p2), angle=0 if chain.axis == "x" else 90,
                                     dimstyle="EZDXF", dxfattribs={"layer": "A-ANNO-DIMS"})
            dim.render()
    doc.saveas(str(out_dxf))
    return out_dxf
