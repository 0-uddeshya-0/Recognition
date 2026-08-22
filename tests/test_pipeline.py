"""End-to-end tests on the public sample models.

These are the harness's own verifier: Devin must keep them green.
"""
from pathlib import Path

import ezdxf
import pytest

from recognition import cli, drawings, model as M, rules, schedules

ROOT = Path(__file__).resolve().parent.parent
FZK = ROOT / "samples" / "AC20-FZK-Haus.ifc"
DUPLEX = ROOT / "samples" / "Duplex.ifc"


@pytest.fixture(scope="module")
def fzk():
    return M.load(FZK)


@pytest.fixture(scope="module")
def duplex():
    return M.load(DUPLEX)


def test_inventory(fzk):
    assert fzk.schema == "IFC4"
    assert [s.name for s in fzk.storeys] == ["Erdgeschoss", "Dachgeschoss"]
    assert (len(fzk.walls), len(fzk.spaces), len(fzk.doors), len(fzk.windows)) == (13, 7, 5, 11)


def test_external_inference(fzk):
    # FZK has no Pset_WallCommon.IsExternal; the envelope inference must still find the 4 perimeter walls per storey
    assert sum(1 for w in fzk.walls if w.is_external) >= 4
    assert all(w.is_external is not None for w in fzk.windows)
    assert sum(1 for w in fzk.windows if w.is_external) == len(fzk.windows)  # every FZK window is in a perimeter wall


def test_tags_are_deterministic(fzk):
    again = M.load(FZK)
    assert [s.tag for s in fzk.spaces] == [s.tag for s in again.spaces]
    assert [d.tag for d in fzk.doors] == [d.tag for d in again.doors]
    assert fzk.spaces[0].tag.startswith("R-") and fzk.doors[0].tag.startswith("D-")


def test_room_schedule(fzk):
    rows = schedules.room_schedule(fzk)
    assert len(rows) == 7
    living = next(r for r in rows if r["name"] == "Wohnen")
    assert living["category"] == "living"
    assert living["area_m2"] == pytest.approx(26.0, abs=0.1)
    assert living["doors"]  # connected to at least one door


def test_rules_pass_on_fzk(fzk):
    report = rules.check(fzk)
    assert report.summary()["checks"] > 20
    assert report.errors == []


def test_rules_catch_narrow_duplex_doors(duplex):
    report = rules.check(duplex)
    narrow = [r for r in report.errors if r.rule_id == "DOOR-MIN-WIDTH"]
    assert len(narrow) >= 4
    assert any(r.value == pytest.approx(0.762, abs=0.001) for r in narrow)


def test_ruleset_declares_only_implemented_rules():
    rs = rules.load_ruleset()
    assert set(r["id"] for r in rs["rules"]) <= set(rules.REGISTRY)


def test_drawings(fzk, tmp_path):
    st = fzk.storeys[0]
    svg = drawings.plan_svg(fzk, st, tmp_path / "A-101.svg", sheet_no="A-101", revision="test")
    text = svg.read_text(encoding="utf-8")
    assert "A-101" in text and "R-02" in text and "FLOOR PLAN" in text
    drawings.svg_to_png(svg, tmp_path / "A-101.png")
    assert (tmp_path / "A-101.png").stat().st_size > 10_000
    dxf = drawings.plan_dxf(fzk, st, tmp_path / "A-101.dxf")
    doc = ezdxf.readfile(str(dxf))
    assert {"A-WALL", "A-DOOR", "A-GLAZ", "A-ANNO-DIMS"} <= {l.dxf.name for l in doc.layers}
    assert len(list(doc.modelspace().query("ARC"))) == len(fzk.doors_on(st.name))


def test_cli_run(tmp_path):
    out = tmp_path / "out"
    assert cli.main(["run", str(FZK), str(out), "--revision", "test"]) == 0
    summary = (out / "summary.json").read_text(encoding="utf-8")
    assert '"status": "PASS"' in summary
    for rel in ("report.md", "schedules/doors.csv", "sheets/A-101_Erdgeschoss.pdf", "sheets/A-101_Erdgeschoss.dxf", "model.detailed.ifc"):
        assert (out / rel).exists(), rel


def test_cli_check_gate():
    assert cli.main(["check", str(FZK)]) == 0
    assert cli.main(["check", str(DUPLEX)]) == 1
