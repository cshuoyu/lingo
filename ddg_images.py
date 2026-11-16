"""DuckDuckGo image search — web-wide, no API key required.

Two-step protocol:
  1. GET the search page to pull a `vqd` token
  2. GET /i.js?q=...&vqd=... to fetch JSON results

SafeSearch is disabled by passing `kp=-2` on the page-fetch URL AND `p=-2`
on the i.js call. DDG appears to bind the SafeSearch mode to the vqd at
issue time — if the vqd was minted without kp=-2, later i.js calls with
p=-2 silently fall back to the safe result set.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 30

# DuckDuckGo's documented size buckets
SIZES = ("Wallpaper", "Large", "Medium", "Small", "")

_VQD_PATTERNS = (
    re.compile(r'vqd=["\']([^"\']+)["\']'),
    re.compile(r'vqd=([0-9][\w-]+)'),
)


@dataclass
class DdgImage:
    title: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    source: str
    page_url: str


def _get(url: str, *, referer: str = "") -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _fetch_vqd(query: str) -> str:
    url = "https://duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "iax": "images", "ia": "images", "kp": "-2"}
    )
    html = _get(url).decode("utf-8", errors="replace")
    for pat in _VQD_PATTERNS:
        m = pat.search(html)
        if m:
            return m.group(1)
    raise RuntimeError("Could not extract vqd token from DuckDuckGo")


def search(
    query: str,
    *,
    size: str = "Large",
    start: int = 0,
    vqd: str | None = None,
) -> tuple[list[DdgImage], str, bool]:
    """Run one DDG image search call.

    Returns (results, vqd_token, has_more). Pass the returned vqd back in for
    subsequent pages to avoid re-fetching the token.
    """
    if not vqd:
        vqd = _fetch_vqd(query)
    size_filter = f",,,,,,size:{size}" if size else ""
    params = {
        "l": "us-en",
        "o": "json",
        "q": query,
        "vqd": vqd,
        "f": size_filter,
        "p": "-2",
        "s": str(start),
    }
    url = "https://duckduckgo.com/i.js?" + urllib.parse.urlencode(params)
    try:
        data = _get(url, referer="https://duckduckgo.com/")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DDG error {e.code}: {body[:200]}") from e
    obj = json.loads(data)
    results: list[DdgImage] = []
    for it in obj.get("results") or []:
        img = it.get("image", "").strip()
        if not img:
            continue
        results.append(DdgImage(
            title=(it.get("title") or "").strip(),
            image_url=img,
            thumb_url=(it.get("thumbnail") or "").strip(),
            width=int(it.get("width") or 0),
            height=int(it.get("height") or 0),
            source=(it.get("source") or "").strip(),
            page_url=(it.get("url") or "").strip(),
        ))
    has_more = bool(obj.get("next"))
    return results, vqd, has_more
