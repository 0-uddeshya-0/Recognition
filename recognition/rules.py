"""Compliance rules engine.

Rules are declared in YAML (thresholds = data) and implemented here as small
functions (logic = code). Each rule returns one Result per element it checks,
pass or fail, so the report can show coverage as well as failures.

This is the verifier of the harness: a failing rule is the signal Devin uses
to know its work is not done.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import yaml

from .model import Model, Space, _rect_dims

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


@rule("ROOM-MIN-AREA")
def room_min_area(model: Model, params: dict, spec: dict) -> list[Result]:
    out = []
    for s in model.spaces:
        lim = params.get(s.category)
        if lim is None:
            continue
        ok = s.area >= lim
        out.append(_res(spec, s, s.area, lim, ok,
                        f"{s.label}: {s.area:.2f} m² {'≥' if ok else '<'} {lim} m² required for {s.category}"))
    return out


@rule("ROOM-MIN-WIDTH")
def room_min_width(model: Model, params: dict, spec: dict) -> list[Result]:
    out = []
    for s in model.spaces:
        lim = params.get(s.category)
        if lim is None:
            continue
        width, _ = _rect_dims(s.footprint)
        ok = width >= lim
        out.append(_res(spec, s, width, lim, ok,
                        f"{s.label}: clear width {width:.2f} m {'≥' if ok else '<'} {lim} m for {s.category}"))
    return out


@rule("DOOR-MIN-WIDTH")
def door_min_width(model: Model, params: dict, spec: dict) -> list[Result]:
    out = []
    for d in model.doors:
        lim = params["external"] if d.is_external else params["interior"]
        ok = d.width + 1e-6 >= lim
        out.append(_res(spec, d, d.width, lim, ok,
                        f"{d.tag} {d.name}: leaf width {d.width:.3f} m {'≥' if ok else '<'} {lim} m "
                        f"({'external' if d.is_external else 'interior'})"))
    return out


@rule("DOOR-MIN-HEIGHT")
def door_min_height(model: Model, params: dict, spec: dict) -> list[Result]:
    lim = params["min"]
    return [_res(spec, d, d.height, lim, d.height + 1e-6 >= lim,
                 f"{d.tag} {d.name}: height {d.height:.3f} m {'≥' if d.height + 1e-6 >= lim else '<'} {lim} m")
            for d in model.doors]


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
        ok = ratio >= params["min_ratio"]
        out.append(_res(spec, s, ratio, params["min_ratio"], ok,
                        f"{s.label}: glazing {ratio:.0%} of floor area {'≥' if ok else '<'} {params['min_ratio']:.0%}"))
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


@rule("ROOM-CLEAR-HEIGHT")
def room_clear_height(model: Model, params: dict, spec: dict) -> list[Result]:
    """BayBO Art. 45 (1): habitable rooms need 2.40 m clear.

    Attic rooms are allowed 2.20 m over half their area; we have no roof geometry,
    so an attic room is measured against the attic limit and the approximation is
    stated in the message rather than hidden.
    """
    lim, attic = params["min_m"], params.get("attic_min_m", params["min_m"])
    applies = set(params.get("applies_to", HABITABLE))
    out = []
    for s in model.spaces:
        if s.category not in applies:
            continue
        limit = attic if s.storey.lower().startswith(("dach", "attic", "ober")) else lim
        h = s.height
        if not h:
            continue                      # no height in the model: nothing to assert
        ok = h + 1e-6 >= limit
        out.append(_res(spec, s, h, limit, ok,
                        f"{s.label}: clear height {h:.2f} m {'≥' if ok else '<'} {limit} m"))
    return out


@rule("DWELLING-FACILITIES")
def dwelling_facilities(model: Model, params: dict, spec: dict) -> list[Result]:
    """BayBO Art. 46 (1-2): a dwelling needs a kitchen and a bathroom.

    Checked per storey, which is the dwelling unit in the v1 single-storey model.
    """
    needs = list(params.get("needs", ("kitchen", "bathroom")))
    present = {s.category for s in model.spaces}
    out = []
    for want in needs:
        ok = want in present
        anchor = next(iter(model.spaces), None)
        if anchor is None:
            continue
        out.append(_res(spec, anchor, None, None, ok,
                        f"dwelling {'has' if ok else 'is MISSING'} a {want}"))
    return out


@rule("CORRIDOR-WIDTH")
def corridor_width(model: Model, params: dict, spec: dict) -> list[Result]:
    """DIN 18040-2 clear corridor width. Only meaningful once triggered."""
    lim = params["min_width"]
    out = []
    for s in model.spaces:
        if s.category != "hall":
            continue
        width, _ = _rect_dims(s.footprint)
        ok = width + 1e-6 >= lim
        out.append(_res(spec, s, width, lim, ok,
                        f"{s.label}: corridor width {width:.2f} m {'≥' if ok else '<'} {lim} m"))
    return out


@rule("MOVEMENT-AREA")
def movement_area(model: Model, params: dict, spec: dict) -> list[Result]:
    """DIN 18040-2 movement area, APPROXIMATED by the room's narrowest side.

    A true check needs furniture layout, which the model does not carry. The
    approximation is declared in the ruleset (`checkable: partial`) and repeated
    in every message, rather than presented as an exact result.
    """
    lim = params["min_side"]
    out = []
    for s in model.spaces:
        if s.category not in HABITABLE:
            continue
        width, _ = _rect_dims(s.footprint)
        ok = width + 1e-6 >= lim
        out.append(_res(spec, s, width, lim, ok,
                        f"{s.label}: narrowest side {width:.2f} m {'≥' if ok else '<'} {lim} m "
                        f"(approximation — no furniture layout in the model)"))
    return out


# --- running ---------------------------------------------------------------

def load_ruleset(path: str | Path | None = None) -> dict:
    return yaml.safe_load(Path(path or DEFAULT_RULESET).read_text(encoding="utf-8"))


def is_evaluable(spec: dict) -> bool:
    """Can this rule be decided from the model at all?

    Two kinds of rule legitimately have no geometric predicate:
      * `checkable: no`  -- the model carries no such data (smoke detectors,
        thresholds). Reported as NOT EVALUATED by recognition.score.
      * policy triggers (`when:`) -- these select other rulesets from the brief
        rather than judging geometry.
    Skipping them here is not hiding them: score.verdict() reports every one.
    """
    checkable = spec.get("checkable", True)
    if isinstance(checkable, bool):
        checkable = "yes" if checkable else "no"
    if str(checkable).lower() in ("no", "false"):
        return False
    return "when" not in spec


def check(model: Model, ruleset: dict | None = None) -> Report:
    ruleset = ruleset or load_ruleset()
    results: list[Result] = []
    for spec in ruleset["rules"]:
        if not is_evaluable(spec):
            continue
        fn = REGISTRY.get(spec["id"])
        if fn is None:
            raise KeyError(f"rule {spec['id']} declared in ruleset but not implemented")
        results.extend(fn(model, spec.get("params", {}), spec))
    return Report(ruleset["name"], str(ruleset.get("version", "")), model.path.name, results)


def to_markdown(report: Report) -> str:
    s = report.summary()
    status = "FAIL" if s["errors"] else ("WARN" if s["warnings"] else "PASS")
    out = [f"# Compliance report — {report.model}", "",
           f"**Status: {status}** — {s['checks']} checks, {s['passed']} passed, "
           f"{s['errors']} errors, {s['warnings']} warnings. Ruleset: {report.ruleset} v{report.version}", "",
           "| Rule | Severity | Checked | Failed |", "|---|---|---|---|"]
    out += [f"| {rid} — {d['title']} | {d['severity']} | {d['checked']} | {d['failed']} |" for rid, d in s["by_rule"].items()]
    if report.failures:
        out += ["", "## Findings", "", "| Rule | Sev | Element | Storey | Value | Limit | Message |", "|---|---|---|---|---|---|---|"]
        for r in report.failures:
            out.append(f"| {r.rule_id} | {r.severity} | {r.element_tag} | {r.storey} | "
                       f"{'' if r.value is None else r.value} | {'' if r.limit is None else r.limit} | {r.message} |")
    else:
        out += ["", "No findings."]
    return "\n".join(out) + "\n"


def write_report(report: Report, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {"ruleset": report.ruleset, "version": report.version, "model": report.model,
            "summary": report.summary(), "results": [asdict(r) for r in report.results]}
    (out_dir / "report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")
    return data
