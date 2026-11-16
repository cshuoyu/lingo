"""Bing image search with local size filtering and unfiltered pagination."""

from __future__ import annotations

import json
import zlib
from html.parser import HTMLParser
import urllib.parse
from dataclasses import dataclass

from http_client import fetch_bytes

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT = 12

SIZES = ("wallpaper", "large", "medium", "small", "")
PAGE_SIZE = 35


@dataclass
class BingImage:
    title: str
    image_url: str
    thumb_url: str
    width: int
    height: int
    source: str
    page_url: str


class BingPage(list[BingImage]):
    """Filtered results carrying the offset in the unfiltered source page."""
    def __init__(self, images, *, next_start: int, scanned_count: int):
        super().__init__(images)
        self.next_start = next_start
        self.scanned_count = scanned_count


def _matches_size(image: BingImage, size: str) -> bool:
    if not size:
        return True
    if not image.width or not image.height:
        return False
    longest = max(image.width, image.height)
    return {
        "wallpaper": image.width >= 1920 and image.height >= 1080,
        "large": longest >= 1280,
        "medium": 500 <= longest < 1280,
        "small": longest < 500,
    }[size]


def _fetch_html(url: str) -> str:
    return fetch_bytes(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bing.com/",
    }, timeout=TIMEOUT).decode("utf-8", errors="replace")


def search(query: str, *, size: str = "wallpaper", start: int = 0) -> tuple[BingPage, bool]:
    """Fetch one source page, then filter locally without changing its offset.

    Bing's qft size filter can return script-only pages for ordinary queries.
    Never send it to the server. Callers paginate with page.next_start, even
    when the selected size leaves no matches in this particular source page.
    """
    if size not in SIZES:
        raise ValueError(f"Unknown Bing image size: {size}")
    if start < 0:
        raise ValueError("Search offset must be nonnegative")
    query = query.strip()
    if not query:
        raise ValueError("Enter a search query")
    params = {"q": query, "first": start, "count": PAGE_SIZE, "adlt": "moderate"}
    errors = []
    no_results = False
    for endpoint in ("async", "search"):
        url = f"https://www.bing.com/images/{endpoint}?" + urllib.parse.urlencode(params)
        try:
            body = _fetch_html(url)
        except (OSError, ValueError, zlib.error) as e:
            errors.append(str(e))
            continue
        images = parse_results(body)
        if images:
            return BingPage(
                [image for image in images if _matches_size(image, size)],
                next_start=start + len(images), scanned_count=len(images),
            ), True
        lowered = body.lower()
        if any(marker in lowered for marker in ("verify you are human", "challenge-form", 'id="b_captcha"')):
            raise RuntimeError("Bing requires browser verification. Open Bing in a browser and retry.")
        no_results |= 'id="nr_indicator"' in lowered or 'id="dg_nr"' in lowered
    if no_results:
        return BingPage([], next_start=start, scanned_count=0), False
    if errors:
        raise RuntimeError("Could not reach Bing: " + errors[-1])
    raise RuntimeError("Bing returned an empty or unsupported page, rather than image results. Please retry.")


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
            link_params = urllib.parse.parse_qs(urllib.parse.urlparse(attrs.get("href") or "").query)
            def dimension(key, fallback):
                try:
                    return int(metadata.get(key) or metadata.get(fallback) or
                               link_params.get("expw" if key == "ow" else "exph", [0])[0])
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
