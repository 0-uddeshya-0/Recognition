# ADR-0002 — The plan→code translator contains no language model

**Status** Accepted · 2026-08-22
**Context layers** L2, L3

## Context

The obvious design is: model reads the brief, model writes the geometry code. That is also
the design that hallucinates — the model invents coordinates that look plausible, and
nothing downstream can tell an invented 4.825 from a derived one.

## Decision

L2 (Architect, a model) emits `ArchitectPlan` containing **relationships and areas but no
coordinates**. L3 (Translator, plain Python, **zero tokens**) turns that plan into
`design/<project>.py`.

Constructs the translator cannot express emit a `# TODO_AGENT:` marker with the plan
fragment attached. Only those markers are ever sent to a model.

## Rationale

Borrowed from [Pan-Chera/Multi-Agent-CAD](https://github.com/Pan-Chera/Multi-Agent-CAD)
(MIT, 869★), whose deterministic `_plan_to_code` translator is credited with a large share
of its 116× token reduction and a *higher* feature pass rate (99.3%) than the LLM-writes-code
baseline. Determinism improved quality; it was not a trade against it.

Two consequences fall out for free:

1. **Reproducibility.** The same brief always yields the same building, so `pytest` over
   committed examples is a meaningful regression gate — an unexplained diff *is* a bug.
2. **A narrow, explicit escape hatch.** When a model does write geometry, it is visible in
   the diff as a `TODO_AGENT` region rather than hidden among generated numbers.

## Consequences

- Floor-packing (adjacency graph → rectangular layout) is now *our* algorithmic problem, and
  it is the hardest engineering risk in the project. v1 constrains the envelope to a
  rectangle on an orthogonal grid to keep it tractable.
- The Architect must be disciplined into never emitting coordinates. Enforced by the pydantic
  schema — there is no coordinate field to fill.
- Adding expressiveness means writing translator code, not prompting harder. This is the
  intended cost.
