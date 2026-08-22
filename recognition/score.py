"""The arbiter: turn a compliance run into a verdict, and rank candidates.

This module is what lets the system be autonomous. When N agents each produce a
candidate building, *nobody chooses between them* -- this scorer does, from the
deterministic compliance result. No model is consulted, so the choice is
reproducible and auditable.

Two responsibilities:

1. `verdict()` -- join the existing rules engine's results to the tier and
   citation metadata in the YAML, and decide PASS/FAIL. Only `tier: law` and
   *triggered* `tier: standard` rules can fail the build. Guidance never blocks.

2. `rank()` -- order passing candidates. The gate is binary; the ranking is how
   the system picks the best of several legal answers.

The honesty rule lives here too: rules declared `checkable: no` are reported as
NOT EVALUATED and are never counted as passes. A system that hid them would
report "PASS 27/27" and imply a completeness it does not have.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

BLOCKING_TIERS = ("law",)          # standard blocks only once triggered
KNOWN_TIERS = ("law", "standard", "guidance", "house")


class RulesetError(ValueError):
    """A ruleset that cannot be trusted. Loud, never a warning."""


# --------------------------------------------------------------------------
# Ruleset metadata
# --------------------------------------------------------------------------

@dataclass
class RuleMeta:
    id: str
    title: str
    tier: str
    severity: str
    source: dict
    checkable: str = "yes"          # yes | partial | no
    requires: list[str] = field(default_factory=list)
    triggered_by: str | None = None
    not_evaluated_reason: str = ""
    partial_reason: str = ""

    @property
    def blocks(self) -> bool:
        return self.tier in BLOCKING_TIERS

    def citation(self) -> str:
        s = self.source
        for k in ("law", "standard", "guidance", "house"):
            if k in s:
                return str(s[k])
        return "uncited"


def _checkable(value: Any, where: str) -> str:
    """Normalise the `checkable` field.

    YAML 1.1 parses bare `no` as boolean False (and `yes` as True), so
    `checkable: no` arrives here as a bool. Coercing with str() would produce
    "False" and silently drop the rule from the not-evaluated list -- exactly the
    hidden blind spot this field exists to prevent.
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    v = str(value).strip().lower()
    if v in ("yes", "true"):
        return "yes"
    if v in ("no", "false"):
        return "no"
    if v == "partial":
        return "partial"
    raise RulesetError(f"{where}: checkable must be yes, no or partial; got {value!r}")


def load_ruleset(path: str | Path) -> tuple[dict, dict[str, RuleMeta]]:
    """Load a jurisdiction pack, refusing anything without provenance."""
    p = Path(path)
    if not p.exists():
        raise RulesetError(f"ruleset not found: {p}")
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    metas: dict[str, RuleMeta] = {}
    for i, raw in enumerate(doc.get("rules", [])):
        rid = raw.get("id")
        where = f"{p.name} rules[{i}]" + (f" ({rid})" if rid else "")
        if not rid:
            raise RulesetError(f"{where}: rule is missing 'id'")
        # These two are the whole point of the tier system. Refuse to load without.
        if "tier" not in raw:
            raise RulesetError(
                f"{where}: missing 'tier'. Every rule must declare one of {list(KNOWN_TIERS)} "
                "so the system knows whether it may block a merge."
            )
        if raw["tier"] not in KNOWN_TIERS:
            raise RulesetError(f"{where}: unknown tier '{raw['tier']}', expected one of {list(KNOWN_TIERS)}")
        if not raw.get("source"):
            raise RulesetError(
                f"{where}: missing 'source'. A rule without a citation cannot be reported "
                "to a client and must not enter the system."
            )
        metas[rid] = RuleMeta(
            id=rid,
            title=raw.get("title", rid),
            tier=raw["tier"],
            severity=raw.get("severity", "warning"),
            source=raw["source"],
            checkable=_checkable(raw.get("checkable", "yes"), where),
            requires=list(raw.get("requires", [])),
            triggered_by=raw.get("triggered_by"),
            not_evaluated_reason=raw.get("not_evaluated_reason", "").strip(),
            partial_reason=raw.get("partial_reason", "").strip(),
        )
    if not metas:
        raise RulesetError(f"{p}: contains no rules")
    return doc, metas


def required_slots(metas: dict[str, RuleMeta]) -> list[str]:
    """The union of every rule's data requirements -- this drives the interview.

    Nobody maintains a question bank: add a rule with `requires`, and the
    interview covers it on the next run.
    """
    out: set[str] = set()
    for m in metas.values():
        out.update(m.requires)
    return sorted(out)


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------

@dataclass
class Finding:
    rule_id: str
    tier: str
    severity: str
    status: str                     # passed | failed | not_evaluated
    element: str
    message: str
    citation: str
    url: str = ""
    blocking: bool = False


@dataclass
class Verdict:
    """The gate's answer. `ok` is the only thing that decides a merge."""
    candidate: str
    ok: bool
    checked: int
    passed: int
    failed: int
    not_evaluated: int
    blocking_failures: int
    advisory_failures: int
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def coverage_line(self) -> str:
        """Never a bare PASS -- what we could not see is part of the answer."""
        return (f"{self.checked} checked · {self.not_evaluated} not evaluated · "
                f"{self.failed} failed")

    def stamp(self) -> str:
        return "PASS" if self.ok else "FAIL"

    def to_dict(self) -> dict:
        return asdict(self)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return p


def _triggered(meta: RuleMeta, brief: dict | None) -> bool:
    """Is a `standard`-tier rule in force for this brief?"""
    if meta.tier != "standard":
        return True
    if not meta.triggered_by:
        return True
    if not brief:
        return False
    # Only the one expression form the packs actually use, evaluated explicitly
    # rather than with eval(): 'accessibility_tier != none'.
    expr = meta.triggered_by.strip()
    if expr == "accessibility_tier != none":
        return str(brief.get("accessibility_tier", "none")) != "none"
    return False


def verdict(report, metas: dict[str, RuleMeta], *, candidate: str = "candidate",
            brief: dict | None = None, metrics: dict | None = None) -> Verdict:
    """Join a `recognition.rules.Report` to tier metadata and decide.

    `report` is the existing engine's Report -- passed in rather than imported so
    this module stays testable without a model on disk.
    """
    findings: list[Finding] = []
    blocking = advisory = passed = failed = 0

    for r in getattr(report, "results", []):
        meta = metas.get(r.rule_id)
        if meta is None:
            # A result with no metadata cannot be attributed; treat as advisory
            # and say so, rather than silently blocking or silently passing.
            findings.append(Finding(r.rule_id, "unknown", r.severity,
                                    "passed" if r.passed else "failed",
                                    f"{r.element_tag} {r.element_name}",
                                    r.message + " [rule not present in ruleset metadata]",
                                    "uncited"))
            if not r.passed:
                advisory += 1
                failed += 1
            else:
                passed += 1
            continue

        if r.passed:
            passed += 1
            continue

        failed += 1
        is_blocking = meta.blocks or (meta.tier == "standard" and _triggered(meta, brief))
        if is_blocking and meta.severity == "error":
            blocking += 1
        else:
            advisory += 1
        findings.append(Finding(
            rule_id=r.rule_id, tier=meta.tier, severity=meta.severity, status="failed",
            element=f"{r.element_tag} {r.element_name}".strip(),
            message=r.message, citation=meta.citation(),
            url=str(meta.source.get("url", "")),
            blocking=bool(is_blocking and meta.severity == "error"),
        ))

    # Declared blind spots. Reported, never counted as passes.
    not_evaluated = 0
    for meta in metas.values():
        if meta.checkable == "no":
            not_evaluated += 1
            findings.append(Finding(
                rule_id=meta.id, tier=meta.tier, severity=meta.severity,
                status="not_evaluated", element="-",
                message=meta.not_evaluated_reason or "No data in the model for this rule.",
                citation=meta.citation(), url=str(meta.source.get("url", "")),
            ))

    checked = passed + failed
    return Verdict(
        candidate=candidate,
        ok=(blocking == 0),
        checked=checked, passed=passed, failed=failed,
        not_evaluated=not_evaluated,
        blocking_failures=blocking, advisory_failures=advisory,
        findings=findings, metrics=dict(metrics or {}),
    )


def failure_brief(v: Verdict, limit: int = 12) -> str:
    """The repair prompt handed back to an agent. Structured, never a transcript."""
    if v.ok:
        return ""
    lines = [f"{v.blocking_failures} blocking compliance failure(s) in '{v.candidate}':"]
    for f in [x for x in v.findings if x.blocking][:limit]:
        lines.append(f"- [{f.rule_id}] {f.element}: {f.message}  (source: {f.citation})")
    lines.append("Fix by changing the ArchitectPlan or the design DSL, then regenerate. "
                 "Do not edit generated output, and do not change any rule threshold.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Ranking -- how the system picks a winner with nobody in the middle
# --------------------------------------------------------------------------

def score(v: Verdict) -> tuple:
    """Sort key. Lower is better. Only ever applied to candidates that passed.

    Ordering rationale, most to least important:
      1. blocking failures    -- a hard gate; should already be 0 here
      2. advisory failures    -- guidance violations are real quality signal
      3. not evaluated        -- prefer the candidate we can say more about
      4. area efficiency      -- less circulation waste per usable m2
      5. opening count        -- fewer openings is cheaper to build
    """
    m = v.metrics
    return (
        v.blocking_failures,
        v.advisory_failures,
        v.not_evaluated,
        -float(m.get("usable_ratio", 0.0)),
        float(m.get("openings", 0)),
    )


def rank(verdicts: list[Verdict]) -> list[Verdict]:
    """Passing candidates first, best-scoring first. Deterministic, no model."""
    ok = sorted([v for v in verdicts if v.ok], key=score)
    bad = sorted([v for v in verdicts if not v.ok], key=score)
    return ok + bad


def winner(verdicts: list[Verdict]) -> Verdict | None:
    """The candidate to merge, or None if not one of them is legal."""
    ordered = rank(verdicts)
    return ordered[0] if ordered and ordered[0].ok else None
