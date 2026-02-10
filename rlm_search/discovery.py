"""Cascade API port-range discovery."""

from __future__ import annotations

import requests


def _parse_port_range(s: str) -> tuple[int, int]:
    """Parse '8089-8095' or '8091' into a (lo, hi) tuple."""
    s = s.strip()
    if "-" in s:
        lo, hi = s.split("-", 1)
        return int(lo.strip()), int(hi.strip())
    port = int(s)
    return port, port


def _probe_url(url: str, timeout: float = 0.5) -> bool:
    """Return True if *url*/health responds with any HTTP status."""
    try:
        requests.get(f"{url}/health", timeout=timeout)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False


def discover_cascade_url(
    api_url: str,
    host: str,
    port_range: str,
    explicit: bool,
    timeout: float = 0.5,
) -> str:
    """Find a live Cascade API endpoint.

    If *explicit* is True the caller set CASCADE_API_URL explicitly — validate
    that single URL and raise ConnectionError if unreachable.

    Otherwise scan *port_range* on *host* and return the first live URL.
    """
    if explicit:
        if _probe_url(api_url, timeout=timeout):
            return api_url
        raise ConnectionError(f"Cascade API unreachable at explicit URL: {api_url}")

    lo, hi = _parse_port_range(port_range)
    for port in range(lo, hi + 1):
        candidate = f"http://{host}:{port}"
        if _probe_url(candidate, timeout=timeout):
            return candidate

    raise ConnectionError(
        f"Cascade API not found on {host} ports {lo}-{hi}. "
        "Set CASCADE_API_URL or start the Cascade server."
    )
