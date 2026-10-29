"""
Google Ads Expert Worker — Hardened Cloud Edition.
Streamable HTTP (POST /mcp), SSE (GET /sse), Rate Limiting, Obfuscation & Security Guard.
"""
import sys
import os
import json
import time
import hmac
from collections import defaultdict
from urllib.parse import parse_qs
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

host = os.environ.get("MCP_HOST", "0.0.0.0")
port = int(os.environ.get("PORT", os.environ.get("MCP_PORT", "8765")))
auth_token = os.environ.get("MCP_AUTH_TOKEN", "").strip()

bundle_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_bundle.pem")
if os.path.exists(bundle_path):
    os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = bundle_path
    os.environ["SSL_CERT_FILE"] = bundle_path

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

print("=" * 60)
print("Google Ads Expert Worker — Hardened Edition")
print(f"Host: {host} | Port: {port}")
print(f"Auth Token: {'Configured (Protected)' if auth_token else 'Public/Local'}")
print("Security: Non-Root, Rate-Limited, Anti-Indexing, Stealth Root")
print("=" * 60)

from src.mcp_server.worker import mcp

mcp.settings.port = port
mcp.settings.streamable_http_path = "/mcp"

# Desabilita proteção rígida de DNS rebinding para permitir proxy reverso (Traefik/Cloudflare)
if hasattr(mcp.settings, "transport_security"):
    mcp.settings.transport_security.enable_dns_rebinding_protection = False
    mcp.settings.transport_security.allowed_hosts = ["*"]
    mcp.settings.transport_security.allowed_origins = ["*"]

http_app = mcp.streamable_http_app()
sse_app = mcp.sse_app()

# Rate limiting in-memory: máx 120 req / 60s por IP
RATE_LIMIT_MAX = 120
RATE_LIMIT_WINDOW = 60
_ip_request_times = defaultdict(list)

def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    times = _ip_request_times[ip]
    valid_times = [t for t in times if now - t < RATE_LIMIT_WINDOW]
    _ip_request_times[ip] = valid_times
    if len(valid_times) >= RATE_LIMIT_MAX:
        return True
    _ip_request_times[ip].append(now)
    return False

def _verify_token(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.strip(), expected.strip())

async def hybrid_app(scope, receive, send):
    if scope["type"] == "lifespan":
        await http_app(scope, receive, send)
        return

    if scope["type"] != "http":
        await http_app(scope, receive, send)
        return

    path = scope.get("path", "")
    method = scope.get("method", "GET")

    # 1. Endpoint anti-indexação: /robots.txt
    if path == "/robots.txt" and method == "GET":
        body = b"User-agent: *\nDisallow: /\n"
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/plain"),
                (b"content-length", str(len(body)).encode()),
                (b"x-robots-tag", b"noindex, nofollow, noarchive"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    # 2. Health check interno do Coolify/Traefik
    if path in ("/health", "/healthz") and method == "GET":
        body = b'{"status":"ok"}'
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-robots-tag", b"noindex, nofollow, noarchive"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    # 3. Raiz furtiva (Stealth Root): retorna 404 para quem só visitar no navegador
    if path == "/" and method == "GET":
        body = b'{"error":"Not Found"}'
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"x-robots-tag", b"noindex, nofollow, noarchive"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    # 4. Extração de IP e Rate Limiting
    headers = dict(scope.get("headers", []))
    client_ip = (
        headers.get(b"cf-connecting-ip", b"").decode("utf-8", errors="ignore")
        or headers.get(b"x-forwarded-for", b"").decode("utf-8", errors="ignore").split(",")[0].strip()
        or scope.get("client", ("unknown", 0))[0]
    )

    if client_ip and client_ip != "127.0.0.1" and _is_rate_limited(client_ip):
        body = b'{"error":"Too Many Requests"}'
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", b"60"),
                (b"x-robots-tag", b"noindex, nofollow, noarchive"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    # 5. Trava de Autenticação Segura (Timing-Safe)
    if auth_token:
        auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
        custom_header = headers.get(b"x-mcp-token", b"").decode("utf-8", errors="ignore")

        query_str = scope.get("query_string", b"").decode("utf-8", errors="ignore")
        qs = parse_qs(query_str)
        token_in_query = qs.get("token", [""])[0]

        authorized = False
        if auth_header.startswith("Bearer "):
            authorized = _verify_token(auth_header[7:], auth_token)
        if not authorized and custom_header:
            authorized = _verify_token(custom_header, auth_token)
        if not authorized and token_in_query:
            authorized = _verify_token(token_in_query, auth_token)

        if not authorized:
            err_body = b'{"error":"Unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(err_body)).encode()),
                    (b"x-robots-tag", b"noindex, nofollow, noarchive"),
                ],
            })
            await send({"type": "http.response.body", "body": err_body})
            return

    # 6. Roteamento Inteligente
    if path.startswith("/messages"):
        await sse_app(scope, receive, send)
        return

    if path.startswith("/sse") and method == "GET":
        await sse_app(scope, receive, send)
        return

    if path in ("/", "/sse") and method == "POST":
        scope["path"] = "/mcp"

    await http_app(scope, receive, send)

if __name__ == "__main__":
    uvicorn.run(hybrid_app, host=host, port=port, log_level="info")
