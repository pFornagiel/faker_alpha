"""Shared network safety (SSRF protection, bounded streaming HTTP) and CDN CIDR helpers.

Used by `capture.py`, `enrich.py`, and other web-facing modules to ensure every outbound URL
target resolves exclusively to globally routable IP addresses and never streams unbounded bodies.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

# Official Cloudflare IPv4 & IPv6 ranges (https://www.cloudflare.com/ips/)
CLOUDFLARE_CIDRS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        # IPv4
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        # IPv6
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)

# Major non-Cloudflare CDN / edge ranges (exact CIDRs, avoiding overly broad /8 blocks)
OTHER_CDN_CIDRS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        # Fastly
        "151.101.0.0/16",
        "199.232.0.0/16",
        "2a04:4e40::/32",
        "2a04:4e42::/32",
        # Google edge
        "142.250.0.0/15",
        "172.217.0.0/16",
        "216.58.192.0/19",
        "2607:f8b0::/32",
        # Meta / Facebook edge
        "157.240.0.0/16",
        "31.13.24.0/21",
        "31.13.64.0/18",
        "185.60.216.0/22",
        "69.171.224.0/19",
        "129.134.0.0/16",
        "57.144.0.0/14",
        "179.60.192.0/22",
        "2a03:2880::/32",
        # AWS CloudFront
        "13.32.0.0/15",
        "18.154.0.0/15",
        "18.160.0.0/15",
        "52.84.0.0/15",
        "3.160.0.0/14",
        # Akamai (specific edge allocations, NOT all of 23.0.0.0/8)
        "23.32.0.0/11",
        "23.192.0.0/11",
        "104.64.0.0/10",
    )
)

_TEXT_CONTENT_MARKERS = ("html", "text/", "json", "xml", "javascript")


def _parse_ip(ip: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an IP string (stripping brackets/scope IDs and unwrapping IPv4-mapped IPv6)."""
    if not ip or not isinstance(ip, str):
        return None
    raw = ip.strip().strip("[]").split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _is_public_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for globally routable unicast addresses (no loopback/private/link-local/multicast/reserved)."""
    return bool(
        addr.is_global
        and not addr.is_private
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_multicast
        and not addr.is_reserved
        and not addr.is_unspecified
    )


def validate_public_url(url: str) -> tuple[str, list[str]]:
    """Validate that `url` is http(s) and resolves exclusively to public global IP addresses.

    Raises `ValueError` on disallowed schemes, missing hostnames, DNS failures, or any non-global IP.
    Returns `(url, sorted_unique_ips)`.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL must be a non-empty string")
    clean_url = url.strip()
    parsed = urlparse(clean_url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r} (only http/https allowed)")
    host = (parsed.hostname or "").strip()
    if not host:
        raise ValueError("URL is missing a hostname")

    # Handle literal IPv4 / IPv6 addresses without DNS lookup
    literal = _parse_ip(host)
    if literal is not None:
        if not _is_public_ip(literal):
            raise ValueError(f"Non-public IP address blocked: {literal}")
        return clean_url, [str(literal)]

    # Resolve hostname via system DNS
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {host!r}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Host lookup failed for {host!r}: {exc}") from exc

    ips: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        addr = _parse_ip(sockaddr[0])
        if addr is None:
            continue
        if not _is_public_ip(addr):
            raise ValueError(f"Host {host!r} resolved to non-public IP: {addr}")
        ips.add(str(addr))

    if not ips:
        raise ValueError(f"Host {host!r} resolved to no usable IP addresses")
    return clean_url, sorted(ips)


def safe_get(
    session: requests.Session,
    url: str,
    headers: dict | None = None,
    timeout: tuple[float, float] = (5.0, 12.0),
    max_bytes: int = 3_000_000,
    allow_redirects: bool = False,
) -> tuple[requests.Response, bytes]:
    """Perform an SSRF-checked, byte-capped streaming HTTP GET request.

    - Validates `url` (and every redirect hop when `allow_redirects=True`) via `validate_public_url`.
    - Skips reading oversized non-HTML binary responses when `Content-Length > max_bytes`.
    - Caps downloaded bytes at `max_bytes` and always closes the underlying response cleanly.
    """
    cur_url, _ = validate_public_url(url)
    max_hops = 8 if allow_redirects else 0
    seen: set[str] = {cur_url}

    for hop in range(max_hops + 1):
        resp = session.get(cur_url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)
        try:
            if allow_redirects and resp.is_redirect and resp.headers.get("location") and hop < max_hops:
                nxt = urljoin(cur_url, resp.headers["location"].strip())
                nxt, _ = validate_public_url(nxt)
                if nxt in seen:
                    return resp, b""
                seen.add(nxt)
                cur_url = nxt
                continue

            # Skip reading huge non-HTML/non-text binary downloads up front
            ctype = (resp.headers.get("content-type") or "").lower()
            clen_raw = resp.headers.get("content-length")
            if clen_raw and clen_raw.isdigit() and int(clen_raw) > max_bytes:
                if ctype and not any(m in ctype for m in _TEXT_CONTENT_MARKERS):
                    return resp, b""

            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65_536):
                if not chunk:
                    continue
                remaining = max_bytes - total
                if remaining <= 0:
                    break
                if len(chunk) > remaining:
                    chunks.append(chunk[:remaining])
                    total += remaining
                    break
                chunks.append(chunk)
                total += len(chunk)
            return resp, b"".join(chunks)
        finally:
            resp.close()

    raise ValueError(f"Too many redirects while fetching {url}")


def is_cloudflare_ip(ip: str) -> bool:
    """Return True if `ip` falls inside an official Cloudflare CIDR range."""
    addr = _parse_ip(ip)
    if addr is None:
        return False
    return any(addr in net for net in CLOUDFLARE_CIDRS if addr.version == net.version)


def is_cdn_ip(ip: str) -> bool:
    """Return True if `ip` belongs to Cloudflare or another major CDN/edge provider."""
    addr = _parse_ip(ip)
    if addr is None:
        return False
    if any(addr in net for net in CLOUDFLARE_CIDRS if addr.version == net.version):
        return True
    return any(addr in net for net in OTHER_CDN_CIDRS if addr.version == net.version)
