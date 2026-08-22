# ADR-0004 — Static UI on GitHub Pages, GitHub Actions as the backend

**Status** Accepted · 2026-08-22
**Context layers** L7, L8

## Context

The UI must be "hostable on GitHub". GitHub Pages serves static files only: it cannot run
Python, so it cannot run IfcOpenShell, and it cannot hold the Devin API key — anything
shipped to the browser is public.

## Decision

- **UI**: static, on GitHub Pages. IFC is parsed and rendered *in the browser* by
  [`web-ifc`](https://github.com/ThatOpen/engine_web-ifc) (MPL-2.0, WebAssembly) through
  three.js. 2D sheets are already vector SVG.
- **Backend**: GitHub Actions. A design request posts a `repository_dispatch`; the workflow
  runs L1–L5, calls Devin with the key held as a repository secret, commits results, and the
  page reads them from committed artifacts.
- The browser never holds a secret.

## Rationale

`web-ifc` is what makes this viable at all — without in-browser IFC parsing, a serverless 3D
viewer is impossible and a backend becomes mandatory. Actions gives a real Linux runner with
`uv`, ifcopenshell and pytest for zero marginal cost, and a natural place for secrets.

The alternative — the FastAPI service already built on `ui/poc` — is faster and genuinely
interactive, but costs money and stops being "hostable on GitHub".

## Consequences

- **Latency is the trade.** A full run is minutes, not sub-second. Acceptable for a design
  request; poor for a tight edit loop. Mitigation: L3/L4/L5 are seconds locally, so edits run
  in-process and Actions is reserved for Devin work.
- The FastAPI path stays a drop-in upgrade: L0–L6 are untouched by this decision, only the
  transport changes.
- **Live blocker**: the Devin GitHub App has no write access to `0-uddeshya-0/Recognition`.
  The last real run got `403` on both push and fork, so no branch and no PR. This is a repo
  settings change and it is on the critical path for this ADR to be realised.
