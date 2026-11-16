"""Fetch NASA Image of the Day — RSS for latest, HTML scraping for pagination."""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from config import cache_dir

RSS_URLS = (
    "https://www.nasa.gov/feeds/iotd-feed/",
    "https://www.nasa.gov/rss/dyn/image_of_the_day.rss",
)
PAGE_URL = "https://www.nasa.gov/image-of-the-day/"
USER_AGENT = "lingo/0.1 (personal desktop wallpaper tool)"
TIMEOUT = 30


@dataclass
class NasaImage:
    title: str
    link: str
    image_url: str
    description: str
    pub_date: str


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


# ---------- RSS (latest only) ----------

def _parse_rss(data: bytes) -> list[NasaImage]:
    root = ET.fromstring(data)
    items: list[NasaImage] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        img_url = (enclosure.get("url") or "").strip()
        if not img_url:
            continue
        items.append(NasaImage(title=title, link=link, image_url=img_url,
                               description=desc, pub_date=date))
    return items


def fetch_rss(limit: int = 10) -> list[NasaImage]:
    last_err: Exception | None = None
    for url in RSS_URLS:
        try:
            data = _get(url)
            return _parse_rss(data)[:limit]
        except (urllib.error.HTTPError, urllib.error.URLError, ET.ParseError) as e:
            last_err = e
    raise RuntimeError(f"Could not fetch NASA IOTD RSS: {last_err}")


# ---------- HTML listing (paginated, ~40/page) ----------

_ITEM_RE = re.compile(
    r'hds-gallery-item-link[^"]*"\s+href="(https://www\.nasa\.gov/image-article/([^/"]+)/)"'
    r'[^>]*>.*?'
    r'hds-gallery-item-caption[^>]*>([^<]*)</div>.*?'
    r'<img\s+src="(https://[^"]+)"\s+alt="([^"]*)"',
    re.DOTALL,
)

_DATE_IN_URL_RE = re.compile(r"/uploads/(\d{4})/(\d{2})/")


def _slug_to_title(slug: str) -> str:
    return slug.replace("-", " ").strip().title()


def _date_from_img_url(url: str) -> str:
    m = _DATE_IN_URL_RE.search(url)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def fetch_page(page: int = 1) -> list[NasaImage]:
    url = PAGE_URL if page == 1 else f"{PAGE_URL}page/{page}/"
    try:
        html = _get(url).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    items: list[NasaImage] = []
    seen: set[str] = set()
    for href, slug, caption, img, alt in _ITEM_RE.findall(html):
        if img in seen:
            continue
        seen.add(img)
        items.append(NasaImage(
            title=_slug_to_title(slug),
            link=href,
            image_url=img,
            description=(caption or alt).strip(),
            pub_date=_date_from_img_url(img),
        ))
    return items


def fetch_iotd(limit: int = 20) -> list[NasaImage]:
    """Fetch newest entries (page 1 of the HTML listing). Falls back to RSS if scraping fails."""
    try:
        items = fetch_page(1)
        if items:
            return items[:limit]
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        _err = e
    else:
        _err = RuntimeError("HTML listing returned no items")
    try:
        return fetch_rss(limit=limit)
    except RuntimeError as rss_err:
        raise RuntimeError(f"{_err}; and RSS: {rss_err}") from rss_err


# ---------- caching / download ----------

def fetch_cache_dir() -> Path:
    d = cache_dir() / "fetch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(url: str) -> Path:
    basename = Path(urlparse(url).path).name or "image.jpg"
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    return fetch_cache_dir() / f"{h}_{basename}"


def download(url: str, dest: Path | None = None) -> Path:
    target = dest or cache_path(url)
    if target.exists() and target.stat().st_size > 0:
        return target
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, tmp.open("wb") as f:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(target)
    return target
