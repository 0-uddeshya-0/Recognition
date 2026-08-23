# The Studio — L7, the interface

The Studio is where a person meets the autonomous layer, and it behaves like
the product it fronts: **an architect you talk to**, not a dashboard you
operate. One conversation runs the whole arc — describe, clarify, choose,
refine, build — and the machinery (workflows, verifier, merges) stays visible
only as honest progress, never as ceremony.

## The flow

```
say it ──▶ (only-if-needed questions) ──▶ 4 blueprint takes ──▶ talk, redraft
                                                │
                              archive ◀── 3D model ◀── pick one
```

1. **Describe** — plain words in the dock. A deterministic parser understands
   buildings ("3BHK", "an office for my startup", "a small warehouse, 300 m²")
   instantly; the *Devin · live* agent reads anything, relayed through the
   `interview` workflow. Every reply is labelled with the engine that produced
   it, and everything inferred is a visible assumption (the **Specs** drawer).
2. **Draft** — the `draft` workflow designs four structurally different takes
   (compact · linear · open · generous), verifies each against the cited
   ruleset, and ships the round back as **one bundle** on the relay branch:
   sheets and 3D meshes inline. Nothing merges; drafts are proposals.
3. **Choose / refine** — options render as glass cards, sheet first, with a
   quiet code pill (`✓ 28 checks · 2 unchecked` — never a bare pass). Saying
   more redrafts; picking one raises the 3D model on the stage.
4. **Archive** — the real autopilot run re-verifies, merges itself on green,
   and the design joins the portfolio with builder-grade files (IFC/DXF/PDF).

## Where the regulations live

Underneath — which is the product's point, not a concession. Every candidate
is judged by the tiered, cited rule engine before it is shown; the
conversation mentions an issue only when one exists ("the linear take has an
issue — the corridor is 1.15 m — details on its card"), and the **checks
drawer** carries the full truth on tap: what ran, what failed with its
citation and a plain-words fix, and what a model cannot see (never counted as
passing). Verdict colour appears nowhere else.

## The glass

A deliberate reset from the drawing-office board: the scene is a soft
architectural morning (layered gradient + faint drafting grid), and every
surface is translucent glass over it — including the 3D stage, where the
model floats directly on the scene with a soft shadow, no box.

| Token | Value | Role |
|---|---|---|
| glass | `rgba(255,255,255,.42)` + `blur(20px) saturate(1.5)` | every panel |
| strong glass | `rgba(255,255,255,.62)` | anything carrying text |
| ink | `#1b2230` / `#4c5568` | type |
| accent | `#3b5bdb` cobalt | the one action colour |
| pass / fail | `#157347` / `#c0392f` | the code pill and drawer, nothing else |
| display | Bricolage Grotesque | headlines, card names |
| body | Sora | conversation, UI |
| data | IBM Plex Mono | every number, dimension and label |

Rules that keep it honest and calm: text sits only on strong glass (≥4.5:1),
motion is 160–320 ms transform/opacity and collapses under
`prefers-reduced-motion`, the idle 3D orbit stops at first touch, and no
progress step ever ticks without a real event (dispatch, CI job step, merge,
deploy) behind it.

## No secret in the page, ever

The published page carries **no credential of any kind**, and still starts
real runs. Three paths, in the order the page prefers them:

1. **The relay** (default, and what the live demo uses) — a Cloudflare Worker
   holding the GitHub token as a Worker secret. It starts one of three
   allow-listed workflows and answers four read shapes (`?runs=`, `?run=`,
   `?jobs=`, `?file=`), each pattern-validated, on this repository only.
   Deploy: `cd infra && CLOUDFLARE_API_TOKEN=… ./deploy.sh <github_pat_…>`,
   then set `config.triggerUrl`.
2. **A personal token** — pasted into Connect, stored in that browser alone,
   sent only to `api.github.com`. Takes precedence over the relay.
3. **A demo key by link** — `…/#k=github_pat_…`; the page stores it locally
   and strips it from the address bar. A fragment never reaches a server and
   never enters git, which is the point: a GitHub token *committed* to a
   public repo is auto-revoked by secret scanning within moments.

With none of the three, the page still works — it hands over the exact
`gh workflow run` command, folded away, and live-follows whatever starts.
Any 401 drops the offending credential, says so, and degrades rather than
breaking. The Devin API key exists only as a repository secret, used inside
workflows, and interview sessions carry an ACU ceiling so a publicly
reachable trigger cannot run up an unbounded bill.

Why the relay proxies *reads* as well: an anonymous browser gets 60 GitHub
API calls an hour, and one run's progress polling exhausts that — the
drafting card would sit on its first step looking stalled while the round
was in fact fine.

**Cache discipline.** GitHub Pages serves assets with a ten-minute max-age,
so `index.html` references `glass.css?v=N`, `config.js?v=N` and `app.js?v=N`.
Bump `N` in the same commit as any `web/` change, or a visitor can run the
previous build's JS against the new HTML.

```
web/
  index.html      the shell: scene, stage, drawers, dock
  glass.css       the design system above
  app.js          conversation, drafting, options, 3D, portfolio
  data/           archived designs (written by autopilot --publish; never by hand)
```
