#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$SCRIPT_DIR/.env" ] && export $(grep -v '^#' "$SCRIPT_DIR/.env" | xargs)
if [ -z "$UPSTREAM_PROXY" ]; then
    echo "[-] UPSTREAM_PROXY env var is required (e.g. http://user:pass@host:port)"
    exit 1
fi
BUILDER_NAME="proxied"

echo "=== Docker Registry Proxy Setup ==="

# --- 1. Update ~/.docker/config.json with proxy settings ---
echo "[+] Updating ~/.docker/config.json with proxy settings..."
DOCKER_CONFIG="${HOME}/.docker/config.json"
if [ -f "$DOCKER_CONFIG" ]; then
    if command -v python3 > /dev/null; then
        python3 -c "
import json, sys
with open('$DOCKER_CONFIG') as f:
    cfg = json.load(f)
cfg['proxies'] = {
    'default': {
        'httpProxy': '$UPSTREAM_PROXY',
        'httpsProxy': '$UPSTREAM_PROXY',
        'noProxy': 'localhost,127.0.0.1'
    }
}
with open('$DOCKER_CONFIG', 'w') as f:
    json.dump(cfg, f, indent=2)
print('[+] Docker client config updated')
"
    fi
else
    mkdir -p "$(dirname "$DOCKER_CONFIG")"
    cat > "$DOCKER_CONFIG" <<CONF
{
  "proxies": {
    "default": {
      "httpProxy": "$UPSTREAM_PROXY",
      "httpsProxy": "$UPSTREAM_PROXY",
      "noProxy": "localhost,127.0.0.1"
    }
  }
}
CONF
    echo "[+] Docker client config created"
fi

# --- 3. Create buildx builder with proxy ---
echo "[+] Setting up BuildKit builder with proxy..."
if docker buildx inspect "$BUILDER_NAME" > /dev/null 2>&1; then
    echo "[*] Removing existing builder '$BUILDER_NAME'..."
    docker buildx rm "$BUILDER_NAME" 2>/dev/null || true
fi

docker buildx create \
    --name "$BUILDER_NAME" \
    --driver docker-container \
    --driver-opt "env.HTTP_PROXY=$UPSTREAM_PROXY" \
    --driver-opt "env.HTTPS_PROXY=$UPSTREAM_PROXY" \
    --driver-opt "env.http_proxy=$UPSTREAM_PROXY" \
    --driver-opt "env.https_proxy=$UPSTREAM_PROXY" \
    --driver-opt "env.NO_PROXY=localhost" \
    --use

echo "[+] Bootstrapping builder (first pull may take a moment)..."
docker buildx inspect --bootstrap "$BUILDER_NAME"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "The buildx builder '$BUILDER_NAME' is now active with proxy routing."
echo "All docker compose build operations will go through the proxy."
echo ""
echo "Run your build command with:"
echo ""
echo "  export BUILDX_BUILDER=$BUILDER_NAME"
echo "  export HTTP_PROXY=$UPSTREAM_PROXY"
echo "  export HTTPS_PROXY=$UPSTREAM_PROXY"
echo "  docker compose build --no-cache"
echo ""
echo "Or use the full one-liner:"
echo ""
echo "  BUILDX_BUILDER=$BUILDER_NAME HTTP_PROXY=$UPSTREAM_PROXY HTTPS_PROXY=$UPSTREAM_PROXY docker compose --progress=plain build --no-cache"
echo ""
echo "Done."
