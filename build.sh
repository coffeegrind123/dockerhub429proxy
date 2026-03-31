#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$SCRIPT_DIR/.env" ] && export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
if [ -z "$UPSTREAM_PROXY" ]; then
    echo "[-] UPSTREAM_PROXY env var is required (e.g. http://user:pass@host:port)"
    exit 1
fi

export BUILDX_BUILDER=proxied
export HTTP_PROXY="$UPSTREAM_PROXY"
export HTTPS_PROXY="$UPSTREAM_PROXY"
export http_proxy="$UPSTREAM_PROXY"
export https_proxy="$UPSTREAM_PROXY"

if [ -z "$DISCORD_WEBHOOK" ]; then
    echo "[!] Warning: DISCORD_WEBHOOK not set, no notification will be sent"
fi

start=$(date +%s); docker builder prune -af; rm -f errors.log; docker compose --progress=plain build --no-cache 2>&1 | tee errors.log && docker compose up -d && status="✅ Success" || status="❌ Failed"; runtime=$(($(date +%s)-start)); echo "Total runtime: $((runtime/60))m $((runtime%60))s"; [ -n "$DISCORD_WEBHOOK" ] && curl -s -H "Content-Type: application/json" -d "{\"content\":\"$status - Docker build complete! Runtime: $((runtime/60))m $((runtime%60))s\"}" "$DISCORD_WEBHOOK"
