#!/usr/bin/env bash
set -euo pipefail

# Deploy to Vercel via CLI
# Usage: deploy.sh [path] [--prod]
#   path  - directory to deploy (defaults to cwd)
#   --prod - deploy to production (not just preview)

TARGET="${1:-.}"
PROD_FLAG=""

# Check for --prod flag
for arg in "$@"; do
  if [[ "$arg" == "--prod" ]]; then
    PROD_FLAG="--prod"
  fi
done

echo "Deploying ${TARGET}..." >&2

cd "$TARGET"

# Build first if package.json exists
if [[ -f package.json ]]; then
  if command -v pnpm &>/dev/null; then
    pnpm install --frozen-lockfile 2>/dev/null || pnpm install
  else
    npm install
  fi
fi

# Deploy
if [[ -n "$PROD_FLAG" ]]; then
  OUTPUT=$(vercel --yes --prod 2>&1)
else
  OUTPUT=$(vercel --yes 2>&1)
fi

# Extract URL
DEPLOY_URL=$(echo "$OUTPUT" | grep -oE 'https://[a-zA-Z0-9._-]+\.vercel\.app' | head -1)

if [[ -z "$DEPLOY_URL" ]]; then
  echo "❌ Deployment failed!" >&2
  echo "$OUTPUT" >&2
  exit 1
fi

echo "" >&2
echo "✓ Deployment successful!" >&2
echo "URL: $DEPLOY_URL" >&2

if [[ -n "$PROD_FLAG" ]]; then
  echo "Mode: Production" >&2
else
  echo "Mode: Preview" >&2
fi

# JSON output
echo "{\"url\":\"$DEPLOY_URL\",\"mode\":\"${PROD_FLAG:-preview}\"}"
