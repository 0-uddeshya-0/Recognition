/* Page configuration — safe to commit; holds no secret by default.
 *
 * demoKey: OPTIONAL. A deliberately public, deliberately weak fine-grained
 * GitHub token whose ONLY permission is "Actions: read & write" on this one
 * repository. It can start workflow runs (drafts, interviews, archives) and
 * nothing else — it cannot read or write code, branches or secrets. Filling
 * it in gives every visitor the seamless zero-setup flow; leaving it empty
 * makes the page hand out trigger commands instead. Rotate or revoke it from
 * GitHub → Settings → Developer settings → Fine-grained tokens.
 */
window.RECOGNITION_CONFIG = {
  demoKey: "",
};
