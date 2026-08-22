"""Compliance rules engine.

Rules are declared in YAML (thresholds = data) and implemented here as small
functions (logic = code). Each rule returns one Result per element it checks,
pass or fail, so the report can show coverage as well as failures.

This is the verifier of the harness: a failing rule is the signal Devin uses
to know its work is not done.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import yaml

from .geometry import rect_dims
from .model import Model, Space
from .writers import markdown_table, write_json, write_text

DEFAULT_RULESET = Path(__file__).resolve().parent.parent / "rules" / "residential.yaml"
HABITABLE = ("bedroom", "living", "kitchen", "bathroom", "office")


@dataclass
class Result:
    rule_id: str
    severity: str
    title: str
    element_tag: str
    element_name: str
    storey: str
    value: float | None
    limit: float | None
    passed: bool
    message: str


@dataclass
class Report:
    ruleset: str
    version: str
    model: str
    results: list[Result]

    @property
    def failures(self) -> list[Result]:
        return [r for r in self.results if not r.passed]

    @property
    def errors(self) -> list[Result]:
        return [r for r in self.failures if r.severity == "error"]

    @property
    def warnings(self) -> list[Result]:
        return [r for r in self.failures if r.severity == "warning"]

    @property
    def status(self) -> str:
        return "FAIL" if self.errors else ("WARN" if self.warnings else "PASS")

    def summary(self) -> dict:
        by_rule: dict[str, dict] = {}
        for r in self.results:
            d = by_rule.setdefault(r.rule_id, {"checked": 0, "failed": 0, "severity": r.severity, "title": r.title})
            d["checked"] += 1
            d["failed"] += 0 if r.passed else 1
        return {
            "checks": len(self.results), "passed": len(self.results) - len(self.failures),
            "errors": len(self.errors), "warnings": len(self.warnings), "by_rule": by_rule,
        }


RuleFn = Callable[[Model, dict, dict], list[Result]]
REGISTRY: dict[str, RuleFn] = {}


def rule(rule_id: str):
    def deco(fn: RuleFn):
        REGISTRY[rule_id] = fn
        return fn
    return deco


def _res(spec: dict, el, value, limit, passed, msg) -> Result:
    return Result(spec["id"], spec["severity"], spec["title"], el.tag, getattr(el, "label", el.name),
                  el.storey, None if value is None else round(value, 3), limit, passed, msg)


def _at_least(value: float, limit: float, tol: float = 0.0) -> tuple[bool, str]:
    """(passed, comparison sign for the message) for a 'value ≥ limit' check."""
    ok = value + tol >= limit
    return ok, "≥" if ok else "<"


def _per_category(model: Model, params: dict, spec: dict, value_of: Callable[[Space], float],
                  message: Callable[[Space, float, str, float], str]) -> list[Result]:
    """Check every space against the limit declared for its category, if any."""
    out = []
    for s in model.spaces:
        lim = params.get(s.category)
        if lim is None:
            continue
        value = value_of(s)
        ok, sign = _at_least(value, lim)
        out.append(_res(spec, s, value, lim, ok, message(s, value, sign, lim)))
    return out


@rule("ROOM-MIN-AREA")
def room_min_area(model: Model, params: dict, spec: dict) -> list[Result]:
    return _per_category(model, params, spec, lambda s: s.area,
                         lambda s, v, sign, lim: f"{s.label}: {v:.2f} m² {sign} {lim} m² required for {s.category}")


@rule("ROOM-MIN-WIDTH")
def room_min_width(model: Model, params: dict, spec: dict) -> list[Result]:
    return _per_category(model, params, spec, lambda s: rect_dims(s.footprint)[0],
                         lambda s, v, sign, lim: f"{s.label}: clear width {v:.2f} m {sign} {lim} m for {s.category}")


@rule("DOOR-MIN-WIDTH")
def door_min_width(model: Model, params: dict, spec: dict) -> list[Result]:
    out = []
    for d in model.doors:
        lim = params["external"] if d.is_external else params["interior"]
        ok, sign = _at_least(d.width, lim, 1e-6)
        out.append(_res(spec, d, d.width, lim, ok,
                        f"{d.tag} {d.name}: leaf width {d.width:.3f} m {sign} {lim} m "
                        f"({'external' if d.is_external else 'interior'})"))
    return out


@rule("DOOR-MIN-HEIGHT")
def door_min_height(model: Model, params: dict, spec: dict) -> list[Result]:
    lim = params["min"]
    out = []
    for d in model.doors:
        ok, sign = _at_least(d.height, lim, 1e-6)
        out.append(_res(spec, d, d.height, lim, ok,
                        f"{d.tag} {d.name}: height {d.height:.3f} m {sign} {lim} m"))
    return out


@rule("ROOM-DAYLIGHT")
def room_daylight(model: Model, params: dict, spec: dict) -> list[Result]:
    out = []
    applies = set(params.get("applies_to", HABITABLE))
    # assign each window to the single space it serves most
    glazing: dict[str, float] = {}
    for w in model.windows:
        rooms = model.spaces_touching(w)
        if rooms:
            glazing[rooms[0].guid] = glazing.get(rooms[0].guid, 0.0) + w.width * w.height
    for s in model.spaces:
        if s.category not in applies:
            continue
        ratio = glazing.get(s.guid, 0.0) / s.area if s.area else 0.0
        ok, sign = _at_least(ratio, params["min_ratio"])
        out.append(_res(spec, s, ratio, params["min_ratio"], ok,
                        f"{s.label}: glazing {ratio:.0%} of floor area {sign} {params['min_ratio']:.0%}"))
    return out


@rule("ROOM-HAS-DOOR")
def room_has_door(model: Model, params: dict, spec: dict) -> list[Result]:
    exempt = set(params.get("exempt", ()))
    out = []
    for s in model.spaces:
        if s.category in exempt:
            continue
        has = any(s in model.spaces_touching(d) for d in model.doors_on(s.storey))
        out.append(_res(spec, s, None, None, has, f"{s.label}: {'has a door' if has else 'no door found'}"))
    return out


# --- running ---------------------------------------------------------------

def load_ruleset(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or DEFAULT_RULESET).read_text(encoding="utf-8"))


def check(model: Model, ruleset: dict | None = None) -> Report:
    ruleset = ruleset or load_ruleset()
    results: list[Result] = []
    for spec in ruleset["rules"]:
        fn = REGISTRY.get(spec["id"])
        if fn is None:
            raise KeyError(f"rule {spec['id']} declared in ruleset but not implemented")
        results.extend(fn(model, spec.get("params", {}), spec))
    return Report(ruleset["name"], str(ruleset.get("version", "")), model.path.name, results)


def to_markdown(report: Report) -> str:
    s = report.summary()
    out = [f"# Compliance report — {report.model}", "",
           f"**Status: {report.status}** — {s['checks']} checks, {s['passed']} passed, "
           f"{s['errors']} errors, {s['warnings']} warnings. Ruleset: {report.ruleset} v{report.version}", ""]
    out += markdown_table(("Rule", "Severity", "Checked", "Failed"),
                          [(f"{rid} — {d['title']}", d["severity"], d["checked"], d["failed"])
                           for rid, d in s["by_rule"].items()])
    if report.failures:
        out += ["", "## Findings", ""]
        out += markdown_table(("Rule", "Sev", "Element", "Storey", "Value", "Limit", "Message"),
                             [(r.rule_id, r.severity, r.element_tag, r.storey, r.value, r.limit, r.message)
                              for r in report.failures])
    else:
        out += ["", "No findings."]
    return "\n".join(out) + "\n"


def write_report(report: Report, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    data = {"ruleset": report.ruleset, "version": report.version, "model": report.model,
            "summary": report.summary(), "results": [asdict(r) for r in report.results]}
    write_json(out_dir / "report.json", data)
    write_text(out_dir / "report.md", to_markdown(report))
    return data
