"""Unit tests for recognition.drawings: symbol geometry, sheet mapping, dimensions."""
from __future__ import annotations

import math

import ezdxf
import pytest
import svgwrite
from shapely.geometry import Point, Polygon, box

import factories as F
from recognition import drawings as D, model as M


def house() -> M.Model:
    m = F.rect_house()
    M._infer_external(m)
    M._assign_tags(m)
    return m


# --- helpers ---------------------------------------------------------------

@pytest.mark.parametrize("metres,text", [
    (3.625, "3 625"), (0.9, "900"), (12.0, "12 000"), (0.0, "0"), (0.0004, "0"),
])
def test_fmt_mm_renders_millimetres_grouped_by_thousands(metres, text):
    assert D._fmt_mm(metres) == text


@pytest.mark.parametrize("value,expected", [(1.234, 1.23), (1.2349, 1.23), (-0.004, -0.0), (2.005, 2.0)])
def test_snap_rounds_to_centimetres(value, expected):
    assert D._snap(value) == pytest.approx(expected, abs=1e-9)


def test_long_axis_returns_the_centreline_of_the_long_side():
    p0, p1, short = D._long_axis(box(0, 0, 4, 0.3))
    assert short == pytest.approx(0.3)
    assert {p0, p1} == {(0.0, 0.15), (4.0, 0.15)}


def test_long_axis_handles_a_shape_that_is_long_in_y():
    p0, p1, short = D._long_axis(box(0, 0, 0.3, 4))
    assert short == pytest.approx(0.3)
    assert sorted([p0[1], p1[1]]) == [0.0, 4.0]
    assert p0[0] == pytest.approx(0.15) and p1[0] == pytest.approx(0.15)


def test_union_bounds_ignores_empty_geometries():
    assert D._union_bounds([box(0, 0, 1, 1), Polygon(), box(2, 3, 4, 5)]) == (0.0, 0.0, 4.0, 5.0)


# --- door / window symbols --------------------------------------------------

def test_door_symbol_swings_into_the_room_next_to_the_door():
    m = house()
    ext_door = m.doors[0]  # in the south wall, room lies to the north
    sym = D.door_symbol(m, ext_door)
    assert sym.arc_radius == pytest.approx(ext_door.width)
    assert len(sym.arc_points) == 13
    # hinge on the jamb-to-jamb line, leaf tip inside the building
    assert sym.arc_center == sym.leaf[0]
    assert sym.leaf[1][1] > sym.leaf[0][1]
    assert m.spaces[0].footprint.buffer(0.2).contains(Point(sym.leaf[1]))


def test_door_symbol_falls_back_to_the_positive_normal_without_a_room():
    door = F.opening("D", box(2, 0, 3, 0.3), width=1.0)
    m = F.make_model(doors=[door])
    sym = D.door_symbol(m, door)
    # no spaces to probe: swing keeps the left normal, and the arc still spans the leaf
    assert sym.arc_radius == pytest.approx(1.0)
    span = (sym.arc_end_deg - sym.arc_start_deg) % 360
    assert span == pytest.approx(90, abs=1e-6)


def test_door_symbol_arc_runs_counter_clockwise_for_either_swing_side():
    below = F.space("S", box(0, -3, 5, -0.01), name="Wohnen")
    door = F.opening("D", box(2, 0, 3, 0.3), width=1.0)
    m = F.make_model(spaces=[below], doors=[door])
    sym = D.door_symbol(m, door)
    assert sym.leaf[1][1] < sym.leaf[0][1]  # swings south, into the only room
    for x, y in sym.arc_points:
        assert math.hypot(x - sym.arc_center[0], y - sym.arc_center[1]) == pytest.approx(1.0, abs=1e-6)


def test_door_symbol_uses_the_footprint_length_when_the_ifc_has_no_width():
    door = F.opening("D", box(2, 0, 3.4, 0.3), width=0.0)
    sym = D.door_symbol(F.make_model(doors=[door]), door)
    assert sym.arc_radius == pytest.approx(1.4)


def test_window_symbol_draws_two_lines_offset_either_side_of_the_centreline():
    window = F.opening("W", box(1, 5.7, 3, 6.0), kind="window", width=2.0)
    lines = D.window_symbol(window).lines
    assert len(lines) == 2
    ys = sorted({round(p[1], 4) for line in lines for p in line})
    assert ys == [5.79, 5.91]  # centreline 5.85 ± min(short/4, 0.06)
    for (a, b) in lines:
        assert a[0] == pytest.approx(1.0) and b[0] == pytest.approx(3.0)


def test_window_symbol_offset_is_capped_for_thick_walls():
    thin = D.window_symbol(F.opening("W", box(1, 0, 3, 0.08), kind="window"))
    thick = D.window_symbol(F.opening("W", box(1, 0, 3, 0.6), kind="window"))
    thin_gap = abs(thin.lines[0][0][1] - thin.lines[1][0][1])
    thick_gap = abs(thick.lines[0][0][1] - thick.lines[1][0][1])
    assert thin_gap == pytest.approx(0.04)   # short/4 for a 8 cm wall
    assert thick_gap == pytest.approx(0.12)  # capped at 2 x 6 cm


# --- sheet mapping ---------------------------------------------------------

def test_sheet_maps_world_metres_to_millimetres_with_y_flipped():
    sh = D._Sheet((0, 0, 10, 5), 100)
    assert sh.k == pytest.approx(10.0)  # 1 m = 10 mm at 1:100
    x0, y0 = sh.p((0, 0))
    x1, y1 = sh.p((10, 5))
    assert x1 - x0 == pytest.approx(100.0)
    assert y0 - y1 == pytest.approx(50.0)  # y grows upwards in the world, downwards on the sheet


def test_sheet_fits_flag_reflects_the_drawable_area():
    assert D._Sheet((0, 0, 10, 5), 100).fits is True
    assert D._Sheet((0, 0, 60, 40), 100).fits is False


def test_choose_scale_picks_the_first_scale_that_fits():
    assert D._choose_scale((0, 0, 6, 4)).scale == 50
    assert D._choose_scale((0, 0, 20, 12)).scale == 100
    assert D._choose_scale((0, 0, 60, 40)).scale == 200


def test_choose_scale_returns_the_smallest_scale_even_if_nothing_fits():
    sh = D._choose_scale((0, 0, 500, 400))
    assert sh.scale == D.SHEET["scales"][-1] and sh.fits is False


def test_plan_bounds_pads_for_the_dimension_chains():
    m = house()
    minx, miny, maxx, maxy = D._plan_bounds(m, "L0")
    pad = D.SHEET["dim_offsets_m"][1] + 1.0
    assert (minx, miny) == pytest.approx((-pad, -pad))
    assert (maxx, maxy) == pytest.approx((8.5, 6.5))


# --- dimension chains ------------------------------------------------------

def test_dimension_chains_has_an_opening_chain_and_an_overall_chain_per_axis():
    chains = D.dimension_chains(house(), "L0")
    assert [c.axis for c in chains] == ["x", "x", "y", "y"]
    o1, o2 = D.SHEET["dim_offsets_m"]
    assert chains[0].offset == pytest.approx(-o1) and chains[1].offset == pytest.approx(-o2)
    assert chains[1].stations == [0.0, 8.0]   # overall width
    assert chains[3].stations == [0.0, 6.0]   # overall depth


def test_dimension_chain_stations_include_wall_faces_and_external_opening_jambs():
    chains = D.dimension_chains(house(), "L0")
    x_stations = chains[0].stations
    assert x_stations[0] == 0.0 and x_stations[-1] == 8.0
    assert 2.0 in x_stations and 3.0 in x_stations       # jambs of the external door
    assert 1.5 in x_stations and 3.5 in x_stations       # jambs of the window
    assert 5.0 not in x_stations                        # interior wall does not dimension the facade


def test_dimension_chain_skips_interior_openings():
    m = house()
    interior_door = m.doors[1]
    assert interior_door.is_external is False
    y_stations = D.dimension_chains(m, "L0").pop(2).stations
    assert 2.0 not in y_stations and 2.9 not in y_stations


def test_dimension_chain_drops_stations_closer_than_five_centimetres():
    m = house()
    # a sliver of an opening 2 cm from the wall face must not produce its own station
    m.windows.append(F.opening("W-SLIVER", box(0.02, 5.7, 1.0, 6.0), kind="window", width=0.98,
                               is_external=True))
    stations = D.dimension_chains(m, "L0")[0].stations
    assert 0.02 not in stations
    assert all(b - a > 0.05 for a, b in zip(stations, stations[1:]))


def test_svg_dim_chain_draws_nothing_for_a_chain_with_a_single_station(tmp_path):
    dwg = svgwrite.Drawing(str(tmp_path / "empty.svg"))
    before = len(dwg.elements)
    D._svg_dim_chain(dwg, D._Sheet((0, 0, 8, 6), 100), D.DimChain("x", -1.2, [1.0]))
    assert len(dwg.elements) == before
    D._svg_dim_chain(dwg, D._Sheet((0, 0, 8, 6), 100), D.DimChain("x", -1.2, [1.0, 4.0]))
    assert len(dwg.elements) > before


def test_dimension_chains_fall_back_to_all_walls_when_none_is_external():
    m = house()
    for w in m.walls:
        w.is_external = False
    assert D.dimension_chains(m, "L0")[0].stations[-1] == 8.0


# --- output files ----------------------------------------------------------

def test_plan_svg_draws_rooms_openings_tags_and_the_title_block(tmp_path):
    m = house()
    svg = D.plan_svg(m, m.storeys[0], tmp_path / "A-101.svg", project="Unit", sheet_no="A-101", revision="r1")
    text = svg.read_text(encoding="utf-8")
    assert "A-101" in text and "Unit" in text and "REV r1" in text
    assert "FLOOR PLAN — L0" in text
    for tag in ("R-01", "R-02", "D-01", "D-02", "W-01"):
        assert f">{tag}" in text or f"{tag}  " in text
    assert "8 000" in text and "6 000" in text  # overall dimension chains
    assert D.STYLE["wall_fill"] in text and D.STYLE["window"] in text


def test_plan_svg_honours_an_explicit_scale(tmp_path):
    m = house()
    svg = D.plan_svg(m, m.storeys[0], tmp_path / "A.svg", scale=200)
    assert "SCALE 1:200" in svg.read_text(encoding="utf-8")
    auto = D.plan_svg(m, m.storeys[0], tmp_path / "B.svg")
    assert "SCALE 1:50" in auto.read_text(encoding="utf-8")


def test_plan_svg_renders_holes_in_a_footprint_with_the_even_odd_rule(tmp_path):
    ring = Polygon([(0, 0), (8, 0), (8, 6), (0, 6)], [[(1, 1), (7, 1), (7, 5), (1, 5)]])
    m = F.make_model(walls=[F.wall("W-RING", ring)], storey_names=("L0",))
    m.walls[0].is_external = True
    svg = D.plan_svg(m, m.storeys[0], tmp_path / "ring.svg")
    text = svg.read_text(encoding="utf-8")
    assert text.count("fill-rule=\"evenodd\"") >= 1
    assert "M 1" in text.replace("M 1.", "M 1")  # the hole ring was pushed onto the path


def test_svg_to_png_and_pdf_produce_non_trivial_files(tmp_path):
    m = house()
    svg = D.plan_svg(m, m.storeys[0], tmp_path / "A.svg")
    png = D.svg_to_png(svg, tmp_path / "A.png")
    pdf = D.svg_to_pdf(svg, tmp_path / "A.pdf")
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size > 5_000
    assert pdf.read_bytes()[:5] == b"%PDF-" and pdf.stat().st_size > 5_000


def test_plan_dxf_uses_aia_layers_millimetres_and_one_arc_per_door(tmp_path):
    m = house()
    dxf = D.plan_dxf(m, m.storeys[0], tmp_path / "A.dxf")
    doc = ezdxf.readfile(str(dxf))
    msp = doc.modelspace()
    assert doc.header["$INSUNITS"] == 4
    assert set(D.LAYERS) <= {layer.dxf.name for layer in doc.layers}
    assert len(msp.query("ARC")) == len(m.doors)
    assert len(msp.query("LINE[layer=='A-GLAZ']")) == 2 * len(m.windows)
    assert {t.dxf.text for t in msp.query("TEXT[layer=='A-ANNO-TEXT']")} == {"D-01", "D-02"}
    # walls are drawn in millimetres: the 8 m facade is 8000 units wide
    walls = msp.query("LWPOLYLINE[layer=='A-WALL']")
    assert max(p[0] for w in walls for p in w.get_points("xy")) == pytest.approx(8000.0)


def test_plan_dxf_emits_a_polyline_per_hole(tmp_path):
    ring = Polygon([(0, 0), (8, 0), (8, 6), (0, 6)], [[(1, 1), (7, 1), (7, 5), (1, 5)]])
    m = F.make_model(walls=[F.wall("W-RING", ring, is_external=True)], storey_names=("L0",))
    dxf = D.plan_dxf(m, m.storeys[0], tmp_path / "ring.dxf")
    walls = ezdxf.readfile(str(dxf)).modelspace().query("LWPOLYLINE[layer=='A-WALL']")
    assert len(walls) == 2  # exterior ring + hole
