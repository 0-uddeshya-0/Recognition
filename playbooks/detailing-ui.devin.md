# Playbook: detailing request from the Recognition UI

Macro: `!detail-ui`

The architect typed a request into the Recognition web UI and attached a model.
You are the detailer: change the rules or the generator, regenerate, and hand
back a package the UI can render. The UI reads the package from git, so commit
it in a tracked folder.

## Procedure

1. Clone the repo, check out the base branch named in the prompt (`poc/ifc-detailing`
   unless told otherwise), `uv sync`, `uv run pytest -q` — green baseline.
2. Download the attached `.ifc` (the `ATTACHMENT:` line in the prompt) to `out/<name>.ifc`
   (git-ignored; never commit the model).
3. Read the request. Decide what it is:
   - **Threshold change** → edit the value in the ruleset YAML, with a comment citing the request.
   - **New rule** → YAML entry + `@rule("ID")` function in `recognition/rules.py` + a test.
   - **Drawing or vocabulary change** → `recognition/drawings.py` / `recognition/model.py` + a test.
   - **No change requested** → just produce the package.
   If the prompt includes a ruleset in a ```yaml block, save it as `<package_dir>/rules.yaml`
   and pass it with `--rules`; otherwise use `rules/residential.yaml`.
4. Create the branch named in the prompt and run
   `uv run recognition run out/<name>.ifc <package_dir> --project "<project>" [--rules …]`
   where `<package_dir>` is the `deliveries/<name>/` path named in the prompt.
5. Open every PNG under `<package_dir>/sheets/` and read `<package_dir>/report.md`.
   Fix generator gaps you find (unlabelled rooms, swings into walls, rooms categorised `other`
   that clearly are not) — in `recognition/`, never in the output — and regenerate.
6. If `recognition/` or `rules/` changed: regenerate `examples/` for both sample models and
   run `uv run pytest -q`.
7. Commit **the package directory and any code/rule changes** to the branch, push, and open a
   pull request against the base branch. PR body: compliance status line, each sheet PNG as an
   image, the findings table from `report.md`, what you changed and why, assumptions.
8. Call the structured output tool with: `branch`, `pr_url`, `package_dir`, `status`, `checks`,
   `errors`, `warnings`, `sheets`, `changed`, `assumptions`.
9. Stay in the session: the architect may send a follow-up message. On a follow-up, repeat
   steps 3–8 on the same branch and call the structured output tool again.

## Specifications

- `<package_dir>/summary.json` exists on the branch and `uv run pytest -q` passes.
- The PR exists and its description shows the sheets.
- Structured output was called (the UI waits for it).

## Forbidden

- Committing `.ifc` models or anything under `out/`.
- Hand-editing generated files or `samples/`.
- Hard-coding thresholds in Python.
- Merging the PR yourself — the architect approves from the UI.
