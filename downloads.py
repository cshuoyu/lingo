"""Validate image downloads before adding them to a collection."""
import hashlib
from io import BytesIO
from pathlib import Path
import urllib.parse
import urllib.request
from PIL import Image
from collection_ops import copy_image

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
SUFFIXES = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'TIFF': '.tiff', 'BMP': '.bmp', 'GIF': '.gif'}


def download_image(item, destination: Path) -> Path | None:
    request = urllib.request.Request(item.image_url, headers={
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
        'Referer': item.page_url or item.image_url,
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError('Image exceeds the 64 MB download limit')
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
