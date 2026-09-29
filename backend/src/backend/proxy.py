"""Trusted-proxy header normalization (single ASGI layer).

Trust model (two hops, configured separately):
- upstream-proxy -> gateway: Caddy's ``trusted_proxies`` (``TRUSTED_PROXIES``).
- gateway -> backend: this middleware. The backend accepts ``X-Forwarded-For``
  / ``X-Forwarded-Proto`` only when the immediate peer (the gateway container)
  is in ``TRUSTED_PROXIES``. Uvicorn's own ``--proxy-headers`` stays disabled
  (see ``backend/Dockerfile``) so this is the ONE normalization layer.

``TRUSTED_PROXIES`` format: comma-separated IPs/CIDRs, plus the token
``private_ranges`` (RFC1918 + loopback + link-local + CGNAT + IPv6 ULA).
"""

from __future__ import annotations

import ipaddress

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

_PRIVATE_RANGES = (
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "100.64.0.0/10",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)


def parse_trusted_proxies(raw: str | None) -> tuple[list, bool]:
    """Parse TRUSTED_PROXIES into (networks, trust_testclient_token).

    The literal hostname ``testclient`` (Starlette TestClient peer) is only
    trusted when listed explicitly; ``private_ranges`` never covers it.
    """
    networks: list = []
    trust_testclient = False
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        if token == "private_ranges":
            networks.extend(ipaddress.ip_network(c) for c in _PRIVATE_RANGES)
        elif token == "testclient":
            trust_testclient = True
        else:
            networks.append(ipaddress.ip_network(token, strict=False))
    return networks, trust_testclient


def is_trusted_peer(host: str | None, networks: list, trust_testclient: bool = False) -> bool:
    if host == "testclient":
        return trust_testclient
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def resolve_client_ip(
    xff: str | None, peer: str | None, networks: list, trust_testclient: bool = False
) -> str | None:
    """Right-to-left walk: identity is the last untrusted hop.

    The immediate peer must already be trusted (checked by the caller);
    entries at/inside trusted ranges are stripped, forged outer entries
    beyond an untrusted hop are never trusted.
    """
    if not xff:
        return None
    chain = [h.strip() for h in xff.split(",") if h.strip()]
    chain.append(peer or "")
    idx = len(chain) - 1
    while idx > 0 and _hop_trusted(chain[idx], networks, trust_testclient):
        idx -= 1
    candidate = chain[idx]
    return candidate or None


def _hop_trusted(host: str, networks: list, trust_testclient: bool) -> bool:
    return is_trusted_peer(host, networks, trust_testclient)


class ProxyHeadersMiddleware:
    """Normalize scope client/scheme from forwarded headers iff peer trusted."""

    def __init__(self, app: ASGIApp, trusted_proxies: str = "private_ranges") -> None:
        self.app = app
        self.raw = trusted_proxies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            networks, trust_testclient = parse_trusted_proxies(self.raw)
            peer = (scope.get("client") or [None])[0]
            if is_trusted_peer(peer, networks, trust_testclient):
                headers = MutableHeaders(scope=scope)
                xff = headers.get("x-forwarded-for")
                real_ip = resolve_client_ip(xff, peer, networks, trust_testclient)
                if real_ip:
                    port = (scope.get("client") or [None, None])[1]
                    scope["client"] = (real_ip, port)
                proto = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
                if proto in ("http", "https"):
                    scope["scheme"] = proto
        await self.app(scope, receive, send)


__all__ = [
    "ProxyHeadersMiddleware",
    "is_trusted_peer",
    "parse_trusted_proxies",
    "resolve_client_ip",
]
