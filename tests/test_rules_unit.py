"""Unit tests for recognition.rules: each rule function, the report and the runner.

Rules are exercised on synthetic geometry with explicit params so a threshold and
its comparison are tested independently of the demo values in rules/*.yaml.
"""
from __future__ import annotations

import json

import pytest
import yaml
from shapely.geometry import box

import factories as F
from recognition import model as M, rules as R


def spec(rule_id: str, severity: str = "error") -> dict:
    return {"id": rule_id, "severity": severity, "title": f"{rule_id} title"}


def result(rule_id="ROOM-MIN-AREA", passed=True, severity="error", tag="R-01", value=1.0, limit=1.0) -> R.Result:
    return R.Result(rule_id, severity, f"{rule_id} title", tag, "Wohnen", "L0", value, limit, passed, "msg")


# --- individual rules ------------------------------------------------------

def test_room_min_area_compares_area_against_the_limit_for_the_category():
    m = F.make_model(spaces=[
        F.space("S1", box(0, 0, 4, 3), name="Wohnen", category="living"),      # 12 m²
        F.space("S2", box(5, 2, 7, 3.5), name="Bad", category="bathroom"),     # 3 m²
    ])
    M._assign_tags(m)
    results = R.room_min_area(m, {"living": 10.0, "bathroom": 4.0}, spec("ROOM-MIN-AREA"))
    assert [(r.element_tag, r.value, r.limit, r.passed) for r in results] == [
        ("R-01", 12.0, 10.0, True), ("R-02", 3.0, 4.0, False)]
    assert "3.00 m² < 4.0 m² required for bathroom" in results[1].message


def test_room_min_area_skips_categories_the_ruleset_does_not_constrain():
    m = F.make_model(spaces=[F.space("S1", box(0, 0, 1, 1), name="Technik", category="utility")])
    assert R.room_min_area(m, {"living": 10.0}, spec("ROOM-MIN-AREA")) == []


def test_room_min_width_uses_the_clear_width_of_the_rotated_rectangle():
    m = F.make_model(spaces=[F.space("S1", box(0, 0, 6, 1.8), name="Wohnen", category="living")])
    M._assign_tags(m)
    r, = R.room_min_width(m, {"living": 2.0}, spec("ROOM-MIN-WIDTH"))
    assert (r.value, r.limit, r.passed) == (1.8, 2.0, False)
    r_ok, = R.room_min_width(m, {"living": 1.5}, spec("ROOM-MIN-WIDTH"))
    assert r_ok.passed is True


def test_room_min_width_skips_unconstrained_categories():
    m = F.make_model(spaces=[F.space("S1", box(0, 0, 6, 1.8), name="Flur")])
    assert R.room_min_width(m, {"living": 2.0}, spec("ROOM-MIN-WIDTH")) == []


def test_door_min_width_applies_the_external_limit_to_external_doors_only():
    m = F.make_model(doors=[
        F.opening("D1", box(0, 0, 1.0, 0.3), width=1.0, is_external=True),
        F.opening("D2", box(2, 0, 2.8, 0.3), width=0.8, is_external=False),
        F.opening("D3", box(4, 0, 4.8, 0.3), width=0.8, is_external=None),
    ])
    M._assign_tags(m)
    params = {"external": 1.0, "interior": 0.85}
    ext, interior, unknown = R.door_min_width(m, params, spec("DOOR-MIN-WIDTH"))
    assert (ext.limit, ext.passed) == (1.0, True)
    assert (interior.limit, interior.passed) == (0.85, False)
    assert unknown.limit == 0.85  # unknown external flag is treated as interior
    assert "(external)" in ext.message and "(interior)" in interior.message


def test_door_min_width_passes_on_exact_equality_despite_float_noise():
    d = F.opening("D1", box(0, 0, 0.85, 0.3), width=0.85 - 1e-9, is_external=False)
    m = F.make_model(doors=[d])
    M._assign_tags(m)
    r, = R.door_min_width(m, {"external": 1.0, "interior": 0.85}, spec("DOOR-MIN-WIDTH"))
    assert r.passed is True


def test_door_min_height_checks_every_door_against_one_limit():
    m = F.make_model(doors=[
        F.opening("D1", box(0, 0, 0.9, 0.3), height=2.0),
        F.opening("D2", box(2, 0, 2.9, 0.3), height=1.9),
    ])
    M._assign_tags(m)
    tall, short = R.door_min_height(m, {"min": 2.0}, spec("DOOR-MIN-HEIGHT"))
    assert (tall.passed, short.passed) == (True, False)
    assert short.value == 1.9 and short.limit == 2.0


def test_room_daylight_ratio_uses_the_glazing_of_the_windows_serving_the_room():
    m = F.rect_house()
    M._assign_tags(m)
    # window is 2.0 x 1.4 = 2.8 m² of glazing on a 25.38 m² living room -> 11 %
    r, = R.room_daylight(m, {"min_ratio": 0.10, "applies_to": ["living"]}, spec("ROOM-DAYLIGHT"))
    assert r.passed is True and r.value == pytest.approx(0.11, abs=0.005)
    strict, = R.room_daylight(m, {"min_ratio": 0.20, "applies_to": ["living"]}, spec("ROOM-DAYLIGHT"))
    assert strict.passed is False
    assert "%" in strict.message


def test_room_daylight_defaults_to_the_habitable_categories():
    m = F.rect_house()
    M._assign_tags(m)
    tags = [r.element_tag for r in R.room_daylight(m, {"min_ratio": 0.1}, spec("ROOM-DAYLIGHT"))]
    assert len(tags) == 2  # living + bathroom are habitable; a utility room would be skipped
    m.spaces[1].category = "utility"
    assert len(R.room_daylight(m, {"min_ratio": 0.1}, spec("ROOM-DAYLIGHT"))) == 1


def test_room_daylight_ignores_windows_that_serve_no_room():
    m = F.rect_house()
    m.windows.append(F.opening("W-DETACHED", box(30, 30, 32, 30.3), kind="window", width=2.0, height=1.4))
    M._assign_tags(m)
    living, = R.room_daylight(m, {"min_ratio": 0.10, "applies_to": ["living"]}, spec("ROOM-DAYLIGHT"))
    assert living.value == pytest.approx(0.11, abs=0.005)  # the detached window adds no glazing


def test_room_daylight_reports_zero_ratio_for_a_room_without_windows_or_area():
    windowless = F.space("S1", box(0, 0, 3, 3), name="Bad")
    degenerate = F.space("S2", box(10, 10, 13, 13), name="Bad2", category="bathroom", area=0.0)
    m = F.make_model(spaces=[windowless, degenerate])
    M._assign_tags(m)
    for r in R.room_daylight(m, {"min_ratio": 0.1}, spec("ROOM-DAYLIGHT")):
        assert (r.value, r.passed) == (0.0, False)


def test_room_has_door_finds_the_door_of_each_room_and_flags_the_rest():
    m = F.rect_house()
    isolated = F.space("S-ISO", box(20, 20, 23, 23), name="Technik", category="utility")
    m.spaces.append(isolated)
    M._assign_tags(m)
    results = R.room_has_door(m, {}, spec("ROOM-HAS-DOOR"))
    by_tag = {r.element_tag: r.passed for r in results}
    assert by_tag[isolated.tag] is False
    assert all(passed for tag, passed in by_tag.items() if tag != isolated.tag)
    assert all(r.value is None and r.limit is None for r in results)


def test_room_has_door_skips_exempt_categories():
    m = F.rect_house()
    m.spaces.append(F.space("S-ISO", box(20, 20, 23, 23), name="Treppe"))
    M._assign_tags(m)
    results = R.room_has_door(m, {"exempt": ["stair"]}, spec("ROOM-HAS-DOOR"))
    assert "stair" not in {r.element_name for r in results}
    assert len(results) == 2


# --- report ----------------------------------------------------------------

def test_report_partitions_results_into_failures_errors_and_warnings():
    ok = result(passed=True)
    err = result(rule_id="DOOR-MIN-WIDTH", passed=False, severity="error")
    warn = result(rule_id="ROOM-DAYLIGHT", passed=False, severity="warning")
    report = R.Report("rs", "1", "m.ifc", [ok, err, warn])
    assert report.failures == [err, warn]
    assert report.errors == [err]
    assert report.warnings == [warn]


def test_report_summary_counts_per_rule():
    report = R.Report("rs", "1", "m.ifc", [
        result(passed=True), result(passed=False),
        result(rule_id="ROOM-DAYLIGHT", passed=False, severity="warning"),
    ])
    s = report.summary()
    assert (s["checks"], s["passed"], s["errors"], s["warnings"]) == (3, 1, 1, 1)
    assert s["by_rule"]["ROOM-MIN-AREA"] == {"checked": 2, "failed": 1, "severity": "error",
                                             "title": "ROOM-MIN-AREA title"}
    assert s["by_rule"]["ROOM-DAYLIGHT"]["checked"] == 1


def test_result_values_are_rounded_and_labels_prefer_the_long_name():
    s = F.space("S1", box(0, 0, 1, 1), name="R1", long_name="Wohnzimmer")
    s.tag = "R-01"
    r = R._res(spec("ROOM-MIN-AREA"), s, 1.23456, 1.0, True, "msg")
    assert (r.value, r.element_name, r.storey) == (1.235, "Wohnzimmer", "L0")
    assert R._res(spec("ROOM-MIN-AREA"), s, None, None, True, "msg").value is None


# --- runner ----------------------------------------------------------------

def test_load_ruleset_reads_the_default_and_an_explicit_path(tmp_path):
    assert R.load_ruleset()["name"]
    custom = tmp_path / "custom.yaml"
    custom.write_text(yaml.safe_dump({"name": "custom", "version": 2, "rules": []}), encoding="utf-8")
    assert R.load_ruleset(custom) == {"name": "custom", "version": 2, "rules": []}


def test_check_runs_only_the_declared_rules_and_records_the_ruleset_metadata():
    m = F.rect_house()
    M._assign_tags(m)
    ruleset = {"name": "one-rule", "version": 3,
               "rules": [{"id": "DOOR-MIN-HEIGHT", "severity": "error", "title": "H", "params": {"min": 2.0}}]}
    report = R.check(m, ruleset)
    assert (report.ruleset, report.version, report.model) == ("one-rule", "3", "synthetic.ifc")
    assert {r.rule_id for r in report.results} == {"DOOR-MIN-HEIGHT"}
    assert len(report.results) == len(m.doors)


def test_check_raises_for_a_rule_declared_in_yaml_but_not_implemented():
    ruleset = {"name": "rs", "rules": [{"id": "NO-SUCH-RULE", "severity": "error", "title": "?"}]}
    with pytest.raises(KeyError, match="NO-SUCH-RULE"):
        R.check(F.make_model(), ruleset)


def test_check_falls_back_to_the_default_ruleset():
    m = F.rect_house()
    M._assign_tags(m)
    assert {r.rule_id for r in R.check(m).results} <= set(R.REGISTRY)


def test_rule_decorator_registers_the_function():
    @R.rule("TEST-ONLY-RULE")
    def _fn(model, params, spec):  # pragma: no cover - registration is what is asserted
        return []

    try:
        assert R.REGISTRY["TEST-ONLY-RULE"] is _fn
    finally:
        del R.REGISTRY["TEST-ONLY-RULE"]


# --- rendering -------------------------------------------------------------

def test_to_markdown_of_a_clean_report_says_pass_and_no_findings():
    md = R.to_markdown(R.Report("rs", "1", "m.ifc", [result(passed=True)]))
    assert "**Status: PASS**" in md and "No findings." in md
    assert "| ROOM-MIN-AREA — ROOM-MIN-AREA title | error | 1 | 0 |" in md


def test_to_markdown_status_is_warn_when_only_warnings_failed():
    md = R.to_markdown(R.Report("rs", "1", "m.ifc", [result(passed=False, severity="warning")]))
    assert "**Status: WARN**" in md


def test_to_markdown_lists_findings_and_blanks_missing_values():
    report = R.Report("rs", "1", "m.ifc", [result(rule_id="ROOM-HAS-DOOR", passed=False, value=None, limit=None)])
    findings = R.to_markdown(report).split("## Findings")[1]
    assert "**Status: FAIL**" in R.to_markdown(report)
    assert "| ROOM-HAS-DOOR | error | R-01 | L0 |  |  | msg |" in findings


def test_write_report_writes_json_and_markdown(tmp_path):
    report = R.Report("rs", "1", "m.ifc", [result(passed=False)])
    data = R.write_report(report, tmp_path / "out")
    on_disk = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert on_disk == data
    assert data["summary"]["errors"] == 1
    assert data["results"][0]["rule_id"] == "ROOM-MIN-AREA"
    assert (tmp_path / "out" / "report.md").read_text(encoding="utf-8").startswith("# Compliance report — m.ifc")
