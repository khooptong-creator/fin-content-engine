"""URL canonicalization (Part II §3.3).

This is the dedup core: the SHA-256 hash is computed on the *canonicalized* URL,
so the same article from `?utm_source=rss` and `?ref=twitter` collapses into one
item. Keep this module pure (no I/O) — it's the most heavily unit-tested piece.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

# Tracking params stripped before hashing. Conservative list — anything in here
# is assumed to carry zero information about identity.
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "ref",
        "ref_src",
        "ref_url",
        "source",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "ito",
    }
)


def canonicalize_url(raw: str) -> str:
    """Return a canonical URL: https, lowercase host (no www), no trailing slash,
    tracking params stripped, remaining query params sorted."""
    if not raw or not raw.strip():
        return raw
    p = urlparse(raw.strip())

    # Force https. http is upgraded; relative/unknown schemes left alone.
    scheme = "https" if p.scheme in ("http", "https") else (p.scheme or "https")

    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]

    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Keep only non-tracking params; sort for determinism.
    kept = sorted(
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS
    )
    query = urlencode(kept, quote_via=quote)

    # Port preserved only if non-default for the scheme.
    netloc = host
    if p.port and not (
        (scheme == "https" and p.port == 443)
        or (scheme == "http" and p.port == 80)
    ):
        netloc = f"{host}:{p.port}"

    return urlunparse((scheme, netloc, path, "", query, p.fragment or ""))
