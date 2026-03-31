# Docker Hub 429 Proxy

Routes Docker registry pulls through an upstream HTTP proxy (Squid) to bypass Docker Hub rate limits — **without restarting the Docker daemon**.

## How it works

1. Creates a BuildKit builder (`docker-container` driver) with proxy env vars baked in
2. `docker compose build` uses this builder via `BUILDX_BUILDER`, so all base image pulls go through the proxy
3. `~/.docker/config.json` is updated so in-build operations (apt-get, pip, curl in RUN steps) also use the proxy

## Setup

Set your proxy URL and run the setup script:

```bash
export UPSTREAM_PROXY="http://user:pass@host:port"
bash run.sh
```

## Build

After setup, run your build with the proxy builder:

```bash
export BUILDX_BUILDER=proxied
export HTTP_PROXY="http://user:pass@host:port"
export HTTPS_PROXY="http://user:pass@host:port"
docker compose --progress=plain build --no-cache
```

## Environment Variables

### proxy.py

| Variable | Required | Description |
|---|---|---|
| `UPSTREAM_PROXY_HOST` | Yes | Proxy server IP/hostname |
| `UPSTREAM_PROXY_PORT` | Yes | Proxy server port |
| `UPSTREAM_PROXY_USER` | Yes | Proxy auth username |
| `UPSTREAM_PROXY_PASS` | Yes | Proxy auth password |
| `LISTEN_HOST` | No | Local bind address (default: `0.0.0.0`) |
| `LISTEN_PORT` | No | Local listen port (default: `3128`) |

### run.sh

| Variable | Required | Description |
|---|---|---|
| `UPSTREAM_PROXY` | Yes | Full proxy URL, e.g. `http://user:pass@host:port` |

## Files

- `proxy.py` — Chaining forward proxy (Python, stdlib only). Listens locally and tunnels all HTTP/HTTPS through an upstream authenticated proxy.
- `run.sh` — Sets up the BuildKit builder, updates Docker client config, starts the local proxy.
