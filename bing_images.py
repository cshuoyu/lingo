"""Bing image search scraper.

Parse image metadata independently of HTML attribute ordering. Prefer the
regional search endpoint, with international search and pagination fallbacks
when an endpoint returns an empty body. Result metadata is HTML-escaped JSON in the `m` attribute.
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
        "relp": "35",
        "scenario": "ImageBasicHover",
        "layout": "RowBased_Landscape",
    }
    if size and size in _SIZE_QFT:
        params["qft"] = _SIZE_QFT[size]
    bodies = []
    errors = []
    for host, endpoint in (("cn.bing.com", "search"), ("www.bing.com", "async"), ("www.bing.com", "search")):
        request_params = dict(params)
        if endpoint == "search":
            request_params.pop("relp", None)
            request_params.pop("scenario", None)
            request_params.pop("layout", None)
            request_params["form"] = "HDRSC2"
        url = f"https://{host}/images/{endpoint}?" + urllib.parse.urlencode(request_params)
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                body = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError) as e:
            errors.append(str(e))
            continue
        results = parse_results(body)
        if results:
            return results, True
        bodies.append(body)
        lowered = body.lower()
        if any(marker in lowered for marker in ("verify you are human", "challenge-form", 'id="b_captcha"')):
            raise RuntimeError("Bing requires browser verification. Try another search engine.")
    if start > 0 and bodies and not errors:
        return [], False
    if errors and not any(bodies):
        raise RuntimeError("Could not reach Bing: " + errors[-1])
    if any("no results" in body.lower() or "no images" in body.lower() for body in bodies):
        return [], False
    raise RuntimeError("Bing returned an empty or unsupported page. Retry with Any size or use another engine.")


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
