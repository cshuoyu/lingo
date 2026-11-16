from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from PIL import Image
from bing_images import BingImage
from downloads import download_image


class DownloadTests(unittest.TestCase):
    def test_validates_actual_format_and_skips_existing(self):
        image = BytesIO()
        Image.new('RGB', (4, 4), 'blue').save(image, 'PNG')
        response = MagicMock()
        response.__enter__.return_value.read.return_value = image.getvalue()
        item = BingImage('test', 'https://example.org/image.jpg', '', 4, 4, '', '')
        with tempfile.TemporaryDirectory() as root, patch('downloads.urllib.request.urlopen', return_value=response):
            path = download_image(item, Path(root))
            self.assertEqual(path.suffix, '.png')
            self.assertIsNone(download_image(item, Path(root)))

    def test_rejects_html_without_creating_wallpaper(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'<html>Access denied</html>'
        item = BingImage('test', 'https://example.org/image.jpg', '', 0, 0, '', '')
        with tempfile.TemporaryDirectory() as root, patch('downloads.urllib.request.urlopen', return_value=response):
            with self.assertRaises(OSError):
                download_image(item, Path(root))
            self.assertEqual(list(Path(root).iterdir()), [])
