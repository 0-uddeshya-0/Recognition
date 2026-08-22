# Autonomy: where the human is, and where they are not

> This supersedes the interview's position in [README.md](README.md) §2 L1.
> The layers are unchanged; what moved is *when* a person is present.

## The rule

**The human is at the trigger. Never inside the run.**

A system where a person reviews, approves, or corrects intermediate agent output
is a copilot. A layer is a system you point at a problem and come back to an
artifact. The difference is not how good the agent is — it is whether the loop
can close without someone in it.

```
        human                      no human from here on
          │                                   │
   brief ─┴─▶ trigger ──▶ plan ──▶ build ──▶ verify ──▶ merge
                          (Devin)  (0 tok)   (the gate)  (auto)
                                                 │
                              repair ◀───────────┘  fails
```

## What this changed

The interview in L1 was originally interactive: ask the client questions, wait
for answers, then design. That is a human inside the loop. Two changes fix it
without losing the intent-capture the interview was for:

1. **The interview happens before the trigger, not during the run.** It produces
   a sealed `DesignBrief`. Sealing it *is* the trigger.
2. **Nothing blocks on an answer.** Every non-blocking slot the client did not
   fill gets a default and an entry in `assumptions[]`, each carrying the reason
   it was chosen. The run proceeds; the assumptions are visible afterwards and
   editing one re-triggers.

Legal inputs are the exception: a slot required by a `tier: law` rule is never
assumed. If one is missing the brief fails validation and no run starts — which
is a refusal to guess, not a request for approval.

## There is no approve step

The old UI had **Approve & merge**, **Reject**, and **Request a change**. All
three are gone from the autonomous path. In their place:

| Question | Answered by |
|---|---|
| Is this candidate legal? | `score.verdict` — all `tier: law` rules pass |
| Which candidate wins? | `score.rank` — deterministic, no model |
| Should it merge? | The exit code. Green merges; red merges nothing |

`recognition autopilot` exits non-zero when nothing clears the gate, and the
workflow's auto-merge step is `if: success()`. A failed run leaves the artifacts
published and the repository untouched.

## Why a model cannot fake a pass

The obvious attack on an autonomous agent loop is the agent declaring victory.
Three things make that structurally impossible here:

1. **Devin never writes the artifacts it is judged on.** It returns an
   `ArchitectPlan` — areas and adjacencies, no coordinates. The IFC, the sheets
   and the schedules are produced afterwards by `translate` and `design`, which
   contain no model.
2. **Devin never touches the repository.** No branch, no push, no PR. (This also
   happens to route around the standing 403 on the Devin GitHub App, but it is
   the right split regardless.)
3. **The gate reads the artifacts, not the claim.** `score.verdict` runs against
   the built IFC. A session asserting "PASS" in its own output changes nothing.

## The repair loop

A rejected plan does not need a person either. Contract validators are written so
their message *is* the repair instruction:

```
ArchitectPlan.adjacency[0]: 'via' must be 'door' or 'open', got 'opening'
```

That string is sent straight back to the session, which returns a corrected plan.
Observed in the first real run: one rejection, one repair, then a clean pass. A
human only ever sees this if every attempt fails.

Separately, unambiguous vocabulary variants (`opening` → `open`, `WC` →
`bathroom`) are normalised at the boundary and **logged**, so tolerance never
becomes a silent correction.

## Fan-out, and why the siblings must differ

One trigger starts N sessions, each given a structurally different strategy —
compact core, linear frontage, open plan. This is deliberate: three sessions
producing the same building would prove nothing about exploration. Each candidate
is built and verified independently, then ranked:

1. blocking failures (a hard gate, already zero here)
2. advisory failures
3. rules not evaluated — prefer the design we can say more about
4. usable floor ratio
5. opening count — fewer is cheaper to build

A fourth session reviews the winner for what a checker cannot see: a room you
cannot furnish, a door that swings into another, a route that does not work. It
is **advisory by construction** — it annotates, it cannot overturn. A model must
not be able to veto a deterministic gate in either direction.

## What is still honest about the limits

- A candidate that cannot be laid out is recorded as unbuildable and its siblings
  continue. Exploration is allowed to fail.
- Room areas are targets, not guarantees. When a room packs into an unusable
  sliver the envelope grows by a fixed step and the layout retries; the run log
  says the building grew.
- Rules that cannot be checked report NOT EVALUATED. The stamp always carries
  coverage, so no run ever shows a bare PASS.
