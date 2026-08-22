---
name: studio-visual-test
description: Test the Recognition Studio in a real browser, frame by frame — every state, three widths, console clean — before any PR that touches web/.
---

# Studio visual test — frame by frame

The Studio is the product's face. Nothing under `web/` merges on a green unit
suite alone: you must look at it, the way a detailer looks at a drawing.

## Serve it

```bash
python3 -m http.server 8123 -d web        # static — exactly how Pages serves it
```

Open http://localhost:8123 in the browser tool.

## Walk every state, in order

1. **Brief · chat** — the default view. Type a real prose brief ("a house for
   a family of four, three bedrooms, a study, garden to the south").
   Verify: the parsed facts appear as understood-chips, the agent asks only
   questions the rules need, the assumption chips update live, every reply is
   labelled with its engine (rules engine vs Devin), and Design it stays
   disabled until the blocking slots are filled.
2. **Brief · form** — switch modes; the same brief state must be visible.
3. **Working** — without a token: the honest hand-off (brief download + the
   exact command). With a token: the live run tracker ticking real steps.
4. **Result** — 3D orbits, hover names a room and its area, room toggle works,
   edges crisp, no z-fighting; 2D zooms with the wheel and pans by drag,
   double-click resets; PDF link resolves; Compliance tab groups by tier and
   every finding cites its source; Options switches candidates; Code shows
   design.py.
5. **Deep link** — reload `/?p=<project>&c=<candidate>` cold; same result.

## At three widths — every state above

1440 × 900 · 768 × 1024 · 375 × 812. At 375: no horizontal scroll, panes
stack, touch targets ≥ 44 px, the chat composer stays above the fold.

## Console and network

- Zero console errors on every state (warnings: read, then justify or fix).
- No request other than same-origin files, fonts.googleapis/gstatic, the
  pinned three.js CDN, and — only when a token is connected — api.github.com.
  Anything else is a defect.

## Honesty checks (product rules, not style)

- The stamp always carries coverage ("N checked · M not evaluated · K failed")
  — a bare PASS anywhere is a bug.
- Verdict green/red appears only on verdicts, never as decoration.
- No fake progress: every ticking step must correspond to a real event.

## Before the PR

Screenshot each state at each width into `docs/ui/` (named
`<state>-<width>.png`), record one full walkthrough video, attach both. A PR
touching `web/` without current screenshots is not reviewable — do not open it.
