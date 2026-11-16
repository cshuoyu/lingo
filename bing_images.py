"""Bing image search scraper.

Parses `<a class="iusc" m="{…}">` anchors from the search HTML. SafeSearch
is toggled via the `safeSearch=off` URL param; Bing honors it server-side.
Result metadata is embedded as HTML-escaped JSON in the `m` attribute.
"""

from __future__ import annotations

import html
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

# Sizes map to Bing's qft filter values
SIZES = ("wallpaper", "large", "medium", "small", "")
_SIZE_QFT = {
    "wallpaper": "+filterui:imagesize-wallpaper",
    "large": "+filterui:imagesize-large",
    "medium": "+filterui:imagesize-medium",
    "small": "+filterui:imagesize-small",
}

_IUSC_RE = re.compile(r'<a[^>]*class="iusc"[^>]*m="([^"]+)"')


@dataclass
class BingImage:
    title: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    source: str
    page_url: str


def search(
    query: str,
    *,
    size: str = "wallpaper",
    start: int = 0,
) -> tuple[list[BingImage], bool]:
    """Fetch one page of Bing image results.

    `start` is 0-based. Bing serves ~35 results per page; pass
    `start += len(results)` to paginate. Returns (results, has_more).
    """
    params = {
        "q": query,
        "safeSearch": "off",
        "first": str(start + 1),
        "form": "HDRSC2",
    }
    if size and size in _SIZE_QFT:
        params["qft"] = _SIZE_QFT[size]
    # Bing expects '+' in qft literal, not percent-encoded
    url = "https://www.bing.com/images/search?" + urllib.parse.urlencode(
        params, safe="+:"
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Bing error {e.code}") from e

    results: list[BingImage] = []
    for raw in _IUSC_RE.findall(body):
        try:
            m = json.loads(html.unescape(raw))
        except json.JSONDecodeError:
            continue
        img_url = (m.get("murl") or "").strip()
        if not img_url:
            continue
        page = (m.get("purl") or "").strip()
        source = ""
        if page:
            try:
                source = urllib.parse.urlparse(page).netloc
            except ValueError:
                source = ""
        results.append(BingImage(
            title=(m.get("t") or "").strip(),
            image_url=img_url,
            thumb_url=(m.get("turl") or "").strip(),
            width=int(m.get("ow") or m.get("w") or 0),
            height=int(m.get("oh") or m.get("h") or 0),
            source=source,
            page_url=page,
        ))

    has_more = len(results) > 0
    return results, has_more
