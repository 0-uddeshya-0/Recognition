/* The durable seamless trigger: a ~40-line Cloudflare Worker that holds the
 * GitHub token server-side, so the public page needs no key at all.
 *
 * Deploy (≈5 minutes, free tier):
 *   1. dash.cloudflare.com → Workers & Pages → Create Worker → paste this file.
 *   2. Settings → Variables → add two secrets:
 *        GH_TOKEN  — fine-grained token, ONLY this repo, ONLY "Actions: read & write"
 *        REPO      — 0-uddeshya-0/Recognition
 *   3. Deploy, copy the worker URL, put it into web/config.js as triggerUrl,
 *      commit. The page will POST {workflow, inputs} here from then on.
 *
 * The worker only ever starts one of the three known workflows on the one
 * configured repository; a tiny in-memory throttle blunts drive-by spam
 * (per-isolate — enough for a demo window; use KV/Durable Objects for real
 * rate limiting).
 */

const ALLOWED_WORKFLOWS = ["draft.yml", "interview.yml", "autopilot.yml"];
const ALLOWED_ORIGINS = ["https://0-uddeshya-0.github.io", "http://localhost:8123"];
const WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 10;
const hits = new Map();

function cors(origin) {
  const allow = ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0];
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
  };
}

export default {
  async fetch(req, env) {
    const headers = cors(req.headers.get("Origin") || "");
    if (req.method === "OPTIONS") return new Response(null, { headers });
    if (req.method !== "POST") return new Response("POST only", { status: 405, headers });

    const ip = req.headers.get("CF-Connecting-IP") || "unknown";
    const now = Date.now();
    const bucket = (hits.get(ip) || []).filter((t) => now - t < WINDOW_MS);
    if (bucket.length >= MAX_PER_WINDOW) {
      return new Response("slow down", { status: 429, headers });
    }
    bucket.push(now);
    hits.set(ip, bucket);

    const { workflow, inputs } = await req.json().catch(() => ({}));
    if (!ALLOWED_WORKFLOWS.includes(workflow)) {
      return new Response("unknown workflow", { status: 400, headers });
    }
    const r = await fetch(
      `https://api.github.com/repos/${env.REPO}/actions/workflows/${workflow}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "recognition-trigger-relay",
        },
        body: JSON.stringify({ ref: "main", inputs: inputs || {} }),
      },
    );
    // GitHub answers a successful dispatch with 204 No Content, and a 204
    // Response MUST carry a null body — echoing its status with a body of
    // "ok" throws inside the worker (and returns a 1101 to the page). Answer
    // a plain 200 instead; failures pass their status and body straight on.
    if (r.ok) return new Response("ok", { status: 200, headers });
    return new Response(await r.text(), { status: r.status, headers });
  },
};
