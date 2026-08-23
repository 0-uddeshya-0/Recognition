#!/usr/bin/env bash
# Publish the trigger relay and arm it. One argument: the GitHub token the
# relay will use (fine-grained, THIS repo only, "Actions: read & write").
#
#   export CLOUDFLARE_API_TOKEN=…        # "Edit Cloudflare Workers" template
#   ./deploy.sh github_pat_…
#
# Nothing here is written to the repository: the GitHub token becomes a
# Cloudflare Worker secret, and only the resulting worker URL is public.
set -euo pipefail
cd "$(dirname "$0")"

REPO="${REPO:-0-uddeshya-0/Recognition}"
GH_TRIGGER_TOKEN="${1:-}"

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "CLOUDFLARE_API_TOKEN is not set." >&2
  echo "Create one at dash.cloudflare.com → My Profile → API Tokens →" >&2
  echo "Create Token → template 'Edit Cloudflare Workers'." >&2
  exit 1
fi
if [ -z "$GH_TRIGGER_TOKEN" ]; then
  echo "usage: ./deploy.sh <github_pat_…>" >&2
  exit 1
fi

echo "→ publishing the worker"
npx --yes wrangler@latest deploy

echo "→ arming secrets (stored in Cloudflare, never in git)"
printf '%s' "$GH_TRIGGER_TOKEN" | npx --yes wrangler@latest secret put GH_TOKEN
printf '%s' "$REPO"             | npx --yes wrangler@latest secret put REPO

cat <<'DONE'

Deployed. Copy the worker URL printed above into web/config.js:

    window.RECOGNITION_CONFIG = {
      demoKey: "",
      triggerUrl: "https://recognition-trigger.<your-subdomain>.workers.dev",
    };

Commit that (the URL holds no secret) and the plain Studio URL works for
everyone, with the token never leaving Cloudflare.
DONE
