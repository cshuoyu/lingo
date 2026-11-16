"""Validate image downloads before adding them to a collection."""
import hashlib
from io import BytesIO
from pathlib import Path
import urllib.parse
from http_client import fetch_bytes
from PIL import Image
from collection_ops import copy_image

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
SUFFIXES = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'TIFF': '.tiff', 'BMP': '.bmp', 'GIF': '.gif'}


def normalize_image_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Image URL must use HTTP or HTTPS")
    # Quote non-ASCII paths without double-encoding existing URL escapes.
    host = parts.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    if parts.port:
        host += f":{parts.port}"
    return urllib.parse.urlunsplit((
        parts.scheme, host, urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
        urllib.parse.quote(parts.query, safe="%=&:+,/?@!$'()*;~-._"), "",
    ))


def download_image(item, destination: Path) -> Path | None:
    data = fetch_bytes(normalize_image_url(item.image_url), headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
        'Referer': normalize_image_url(item.page_url or item.image_url),
    }, timeout=30, max_bytes=MAX_DOWNLOAD_BYTES)
    with Image.open(BytesIO(data)) as image:
        suffix = SUFFIXES.get(image.format)
        if suffix is None or image.format == 'GIF':
            raise ValueError('Unsupported wallpaper image format')
        image.verify()
    stem = Path(urllib.parse.unquote(urllib.parse.urlparse(item.image_url).path)).stem[:60] or 'image'
    stem = ''.join(c for c in stem if c.isalnum() or c in '-_ ') or 'image'
    digest = hashlib.sha256(item.image_url.encode()).hexdigest()[:12]
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f'{stem}-{digest}{suffix}'
    if target.exists():
        return None
    # Same-directory temporary file allows an atomic, exclusive final copy.
    import tempfile
    with tempfile.TemporaryDirectory(dir=destination, prefix='.download-') as temporary:
        source = Path(temporary) / target.name
        source.write_bytes(data)
        return copy_image(source, destination)
