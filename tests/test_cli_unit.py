"""Unit tests for recognition.cli: argument parsing, summary assembly, IFC enrichment."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue
import pytest

import factories as F
from recognition import cli, model as M, rules as R

ROOT = Path(__file__).resolve().parent.parent
FZK = ROOT / "samples" / "AC20-FZK-Haus.ifc"
DUPLEX = ROOT / "samples" / "Duplex.ifc"


# --- helpers ---------------------------------------------------------------

@pytest.mark.parametrize("raw,slug", [
    ("Erdgeschoss", "Erdgeschoss"),
    ("Level 1", "Level-1"),
    ("T-FDN", "T-FDN"),
    ("  1. OG / Süd  ", "1-OG-S-d"),
    ("---", ""),
])
def test_slug_keeps_only_alphanumerics_and_dashes(raw, slug):
    assert cli._slug(raw) == slug


def test_git_revision_returns_the_short_sha(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "abc1234\n")
    assert cli.git_revision() == "abc1234"


def test_git_revision_is_empty_outside_a_repository(monkeypatch):
    def boom(*a, **k):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "check_output", boom)
    assert cli.git_revision() == ""


# --- argument parsing ------------------------------------------------------

def test_main_requires_a_subcommand():
    with pytest.raises(SystemExit):
        cli.main([])


def test_main_rejects_an_unknown_subcommand():
    with pytest.raises(SystemExit):
        cli.main(["draw", "model.ifc"])


def test_main_run_passes_parsed_arguments_through_to_run(monkeypatch, tmp_path, capsys):
    seen = {}

    def fake_run(model_path, out_dir, rules_path, project, revision):
        seen.update(model_path=model_path, out_dir=out_dir, rules_path=rules_path,
                    project=project, revision=revision)
        return {"model": "m.ifc", "schema": "IFC4", "counts": {"walls": 1},
                "compliance": {"status": "PASS", "checks": 3, "errors": 0, "warnings": 0},
                "sheets": [{"sheet": "A-101", "storey": "L0"}]}

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["run", "m.ifc", str(tmp_path / "out"), "--rules", "r.yaml",
                     "--project", "Haus", "--revision", "rev9"]) == 0
    assert seen == {"model_path": Path("m.ifc"), "out_dir": tmp_path / "out",
                    "rules_path": Path("r.yaml"), "project": "Haus", "revision": "rev9"}
    out = capsys.readouterr().out
    assert "compliance PASS: 3 checks, 0 errors, 0 warnings" in out
    assert "sheets: A-101 L0" in out


def test_main_run_defaults_project_rules_and_revision(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli, "run", lambda *a: seen.update(args=a) or {
        "model": "m", "schema": "IFC4", "counts": {}, "sheets": [],
        "compliance": {"status": "PASS", "checks": 0, "errors": 0, "warnings": 0}})
    cli.main(["run", "m.ifc", str(tmp_path)])
    assert seen["args"][2:] == (None, "", "")


def test_main_check_exit_code_follows_the_error_findings(monkeypatch, capsys):
    m = F.rect_house()
    M._assign_tags(m)
    monkeypatch.setattr(cli.M, "load", lambda path: m)

    monkeypatch.setattr(cli.R, "check", lambda model, ruleset: R.Report("rs", "1", "m.ifc", []))
    assert cli.main(["check", "m.ifc"]) == 0
    assert "**Status: PASS**" in capsys.readouterr().out

    failing = R.Result("DOOR-MIN-WIDTH", "error", "t", "D-01", "d", "L0", 0.7, 0.9, False, "too narrow")
    monkeypatch.setattr(cli.R, "check", lambda model, ruleset: R.Report("rs", "1", "m.ifc", [failing]))
    assert cli.main(["check", "m.ifc"]) == 1
    assert "too narrow" in capsys.readouterr().out


def test_main_check_uses_the_ruleset_given_on_the_command_line(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.M, "load", lambda path: F.make_model())
    monkeypatch.setattr(cli.R, "load_ruleset", lambda path: seen.setdefault("path", path) or {"name": "rs"})
    monkeypatch.setattr(cli.R, "check", lambda model, ruleset: R.Report("rs", "1", "m.ifc", []))
    cli.main(["check", "m.ifc", "--rules", "custom.yaml"])
    assert seen["path"] == Path("custom.yaml")


# --- summary ---------------------------------------------------------------

def test_run_writes_a_summary_that_reports_fail_for_a_model_with_errors(tmp_path):
    summary = cli.run(DUPLEX, tmp_path / "out", None, "Duplex", "rev1")
    on_disk = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert on_disk == summary
    assert summary["compliance"]["status"] == "FAIL"
    assert summary["compliance"]["errors"] > 0
    assert summary["revision"] == "rev1" and summary["project"] == "Duplex"
    assert set(summary["schedules"]) == {"rooms", "doors", "windows"}  # the "dir" key stays internal
    assert summary["schedules"]["rooms"] == summary["counts"]["spaces"]
    assert summary["files"]["enriched_ifc"] == "model.detailed.ifc"
    assert [sh["sheet"] for sh in summary["sheets"]] == [f"A-{100 + i}" for i in range(1, len(summary["sheets"]) + 1)]
    for sh in summary["sheets"]:
        for ext in ("svg", "pdf", "png", "dxf"):
            assert (tmp_path / "out" / "sheets" / sh[ext]).exists()


def test_run_falls_back_to_the_git_revision_and_the_model_stem(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "git_revision", lambda: "deadbee")
    summary = cli.run(FZK, tmp_path / "out", None, "", "")
    assert summary["revision"] == "deadbee"
    assert summary["project"] == "AC20-FZK-Haus"
    assert summary["compliance"]["status"] == "PASS"


# --- IFC enrichment --------------------------------------------------------

def test_enrich_ifc_writes_tags_and_findings_back_into_the_model(tmp_path):
    model = M.load(DUPLEX)
    report = R.check(model)
    failing_tags = {r.element_tag for r in report.failures}
    assert failing_tags, "Duplex is expected to have findings"

    expected = {}
    for r in report.failures:
        expected.setdefault(r.element_tag, []).append(f"{r.rule_id} ({r.severity})")

    out = cli.enrich_ifc(model, report, tmp_path / "nested" / "model.detailed.ifc")
    written = ifcopenshell.open(str(out))
    failed = 0
    for el in model.spaces + model.doors + model.windows:
        pset = ue.get_psets(written.by_guid(el.guid))["Recognition_Detailing"]
        assert pset["Tag"] == el.tag
        assert pset["GeneratedBy"].startswith("Recognition ")
        if el.tag in failing_tags:
            assert pset["ComplianceStatus"] == "FAIL"
            assert pset["Findings"] == "; ".join(expected[el.tag])
            failed += 1
        else:
            assert pset["ComplianceStatus"] == "PASS" and pset["Findings"] == "-"
    assert failed == len(failing_tags)
