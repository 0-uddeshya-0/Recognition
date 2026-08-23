/* Page configuration — safe to commit; must never hold a real secret.
 *
 * demoKey: leave EMPTY in this file. GitHub's secret scanning automatically
 * revokes any GitHub token pushed to a public repository (that is exactly
 * what happened to the first demo key), so a committed key dies on arrival.
 * Hand the key to the page through the URL instead:
 *
 *     https://<pages-url>/#k=github_pat_…
 *
 * The page stores it locally and strips it from the address bar; the
 * fragment never reaches a server and never enters this repository. Mint it
 * as a fine-grained token, THIS repo only, permission "Actions: read &
 * write" and nothing else — it can start workflow runs and do nothing more.
 *
 * triggerUrl: optional, the durable alternative — a tiny relay (see
 * infra/trigger-worker.js) that holds the token server-side. When set, the
 * page POSTs {workflow, inputs} there instead of calling GitHub directly.
 */
window.RECOGNITION_CONFIG = {
  demoKey: "",
  triggerUrl: "",
};
