#!/usr/bin/env python3
"""
HTTP/HTTPS chaining forward proxy.

Listens locally and forwards all requests through an upstream HTTP proxy.
Handles both CONNECT tunneling (HTTPS) and plain HTTP forwarding.
"""

import base64
import logging
import os
import select
import signal
import socket
import sys
import threading
from urllib.parse import urlparse

UPSTREAM_PROXY_HOST = os.environ["UPSTREAM_PROXY_HOST"]
UPSTREAM_PROXY_PORT = int(os.environ["UPSTREAM_PROXY_PORT"])
UPSTREAM_PROXY_USER = os.environ["UPSTREAM_PROXY_USER"]
UPSTREAM_PROXY_PASS = os.environ["UPSTREAM_PROXY_PASS"]

LISTEN_HOST = os.environ.get("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "3128"))

BUFFER_SIZE = 65536
CONNECT_TIMEOUT = 30
RELAY_TIMEOUT = 120

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chainproxy")


def upstream_auth_header():
    creds = f"{UPSTREAM_PROXY_USER}:{UPSTREAM_PROXY_PASS}"
    encoded = base64.b64encode(creds.encode()).decode()
    return f"Basic {encoded}"


def connect_to_upstream():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    sock.connect((UPSTREAM_PROXY_HOST, UPSTREAM_PROXY_PORT))
    return sock


def relay(sock_a, sock_b):
    sockets = [sock_a, sock_b]
    try:
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, RELAY_TIMEOUT)
            if exceptional:
                break
            if not readable:
                break
            for s in readable:
                data = s.recv(BUFFER_SIZE)
                if not data:
                    return
                target = sock_b if s is sock_a else sock_a
                target.sendall(data)
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass


def handle_connect(client_sock, host, port):
    upstream = None
    try:
        upstream = connect_to_upstream()

        connect_req = (
            f"CONNECT {host}:{port} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Proxy-Authorization: {upstream_auth_header()}\r\n"
            f"Proxy-Connection: keep-alive\r\n"
            f"\r\n"
        )
        upstream.sendall(connect_req.encode())

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = upstream.recv(BUFFER_SIZE)
            if not chunk:
                client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return
            response += chunk

        status_line = response.split(b"\r\n")[0].decode(errors="replace")
        status_code = int(status_line.split()[1])

        if status_code != 200:
            log.warning("CONNECT to %s:%s failed: %s", host, port, status_line)
            client_sock.sendall(f"HTTP/1.1 {status_code} Upstream Proxy Error\r\n\r\n".encode())
            return

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        log.info("CONNECT tunnel established: %s:%s", host, port)

        leftover = response.split(b"\r\n\r\n", 1)[1]
        if leftover:
            upstream.sendall(leftover) if False else None
            client_sock.sendall(leftover) if leftover else None

        relay(client_sock, upstream)

    except Exception as e:
        log.error("CONNECT error for %s:%s: %s", host, port, e)
        try:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except OSError:
            pass
    finally:
        if upstream:
            upstream.close()


def handle_http(client_sock, method, url, http_version, header_rest):
    upstream = None
    try:
        upstream = connect_to_upstream()

        has_proxy_auth = False
        new_headers = []
        for line in header_rest.split(b"\r\n"):
            if line.lower().startswith(b"proxy-authorization:"):
                has_proxy_auth = True
                continue
            new_headers.append(line)

        auth_header = f"Proxy-Authorization: {upstream_auth_header()}\r\n".encode()
        request_line = f"{method} {url} {http_version}\r\n".encode()
        rebuilt = request_line + auth_header + b"\r\n".join(new_headers)

        upstream.sendall(rebuilt)

        log.info("HTTP %s %s", method, url[:80])
        relay(client_sock, upstream)

    except Exception as e:
        log.error("HTTP relay error: %s", e)
        try:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except OSError:
            pass
    finally:
        if upstream:
            upstream.close()


def handle_client(client_sock, client_addr):
    try:
        client_sock.settimeout(CONNECT_TIMEOUT)
        data = b""
        while b"\r\n" not in data:
            chunk = client_sock.recv(BUFFER_SIZE)
            if not chunk:
                return
            data += chunk

        first_line_end = data.index(b"\r\n")
        first_line = data[:first_line_end].decode(errors="replace")
        rest = data[first_line_end + 2:]

        parts = first_line.split()
        if len(parts) < 3:
            client_sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return

        method = parts[0]
        target = parts[1]
        http_version = parts[2]

        if method == "CONNECT":
            if b"\r\n\r\n" not in data:
                while b"\r\n\r\n" not in data:
                    chunk = client_sock.recv(BUFFER_SIZE)
                    if not chunk:
                        return
                    data += chunk

            if ":" in target:
                host, port = target.rsplit(":", 1)
                port = int(port)
            else:
                host = target
                port = 443

            handle_connect(client_sock, host, port)
        else:
            if b"\r\n\r\n" not in data:
                while b"\r\n\r\n" not in data:
                    chunk = client_sock.recv(BUFFER_SIZE)
                    if not chunk:
                        return
                    data += chunk

            header_rest = data[first_line_end + 2:]
            handle_http(client_sock, method, target, http_version, header_rest)

    except Exception as e:
        log.error("Client handler error from %s: %s", client_addr, e)
    finally:
        client_sock.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(128)

    log.info(
        "Chaining proxy listening on %s:%d -> upstream %s:%d",
        LISTEN_HOST,
        LISTEN_PORT,
        UPSTREAM_PROXY_HOST,
        UPSTREAM_PROXY_PORT,
    )

    def shutdown(signum, frame):
        log.info("Shutting down...")
        server.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    while True:
        try:
            client_sock, client_addr = server.accept()
            t = threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True)
            t.start()
        except OSError:
            break


if __name__ == "__main__":
    main()
