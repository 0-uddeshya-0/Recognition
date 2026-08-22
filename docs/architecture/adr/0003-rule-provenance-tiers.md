# ADR-0003 — Every rule declares a provenance tier, and only law may block

**Status** Accepted · 2026-08-22
**Context layers** L0, L5

## Context

The existing ruleset mixes statute with planning guidance at the same severity. Auditing it
found `ROOM-MIN-AREA` (bedroom ≥ 9 m²) set to `severity: error`, blocking merges — but BayBO
sets no minimum bedroom area at all. The 9 m² is a *Richtwert*. The system was asserting a
legal requirement that does not exist. Separately, `ROOM-DAYLIGHT` used 0.10 where
BayBO Art. 45 (2) requires 1/8 = 0.125.

## Decision

Every rule must declare `tier: law | standard | guidance | house` and a `source` block with
article, URL and `retrieved` date. A rule missing either is a **load error, hard stop**.

Only `tier: law` — and `tier: standard` once triggered — may block a merge. Guidance and
house rules inform and never block.

No LLM may author, edit or extend a rule. Devin may implement a rule's *predicate* in Python
and write its tests, because those are verifiable by execution; it may never author the
threshold or the citation.

## Rationale

"No hallucination" for a compliance system means more than not inventing numbers — it means
never overstating the authority behind a number that is correct. A warning that a bedroom is
small is useful. The same warning stamped as a legal error is a false claim about German law,
and it is the kind of error a client would act on.

Tiers also make the UI honest: a guidance warning must never look like a legal error.

## Consequences

- Phase 0 work: backfill `tier` and `source` across the existing pack, correct the daylight
  ratio to 1/8, demote `ROOM-MIN-AREA` to guidance.
- `retrieved` dates enable drift control — a scheduled job flags citations older than
  12 months for human re-verification.
- Adding a jurisdiction is adding a pack directory, not changing code.
