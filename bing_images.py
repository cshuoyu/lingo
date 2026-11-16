"""Bing image search scraper.

Parses `<a class="iusc" m="{…}">` anchors from the search HTML. SafeSearch
is toggled via the `safeSearch=off` URL param; Bing honors it server-side.
Result metadata is embedded as HTML-escaped JSON in the `m` attribute.
"""

from __future__ import annotations

import json
from html.parser import HTMLParser
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
    "wallpaper": "filterui:imagesize-wallpaper",
    "large": "filterui:imagesize-large",
    "medium": "filterui:imagesize-medium",
    "small": "filterui:imagesize-small",
}



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
        "count": "35",
        "mmasync": "1",
    }
    if size and size in _SIZE_QFT:
        params["qft"] = _SIZE_QFT[size]
    url = "https://www.bing.com/images/async?" + urllib.parse.urlencode(
        params
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

    results = parse_results(body)
    if not results and start == 0:
        lowered = body.lower()
        if any(marker in lowered for marker in ("captcha", "verify you are human", "challenge-form")):
            raise RuntimeError("Bing requires browser verification. Try another search engine.")
        if not any(marker in lowered for marker in ("no results", "no images", "没有找到")):
            raise RuntimeError("Bing returned no readable image results. Try another engine or size filter.")
    return results, bool(results)


class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self.seen = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "a" or "iusc" not in (attrs.get("class") or "").split():
            return
        try:
            metadata = json.loads(attrs.get("m") or "{}")
            url = (metadata.get("murl") or "").strip()
            if urllib.parse.urlparse(url).scheme not in ("http", "https") or url in self.seen:
                return
            page = (metadata.get("purl") or "").strip()
            def dimension(key, fallback):
                try:
                    return int(metadata.get(key) or metadata.get(fallback) or 0)
                except (TypeError, ValueError):
                    return 0
            self.results.append(BingImage(
                title=(metadata.get("t") or attrs.get("aria-label") or "").strip(),
                image_url=url, thumb_url=(metadata.get("turl") or "").strip(),
                width=dimension("ow", "w"), height=dimension("oh", "h"),
                source=urllib.parse.urlparse(page).netloc, page_url=page,
            ))
            self.seen.add(url)
        except (ValueError, TypeError, AttributeError):
            return


def parse_results(body: str) -> list[BingImage]:
    parser = _ImageParser()
    parser.feed(body)
    return parser.results
