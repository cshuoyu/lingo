import json
import unittest
from unittest.mock import patch
from image_sources import search


class SourceTests(unittest.TestCase):
    def test_wallhaven_continuation(self):
        data = {'data': [{'id': 'abc', 'path': 'https://example.org/a.jpg', 'dimension_x': 1920, 'dimension_y': 1080, 'url': 'https://wallhaven.cc/w/abc'}], 'meta': {'current_page': 2, 'last_page': 3}}
        with patch('image_sources._get', return_value=data) as request:
            results, token, more = search('wallhaven', 'mountain', size='Wallpaper', token='2')
        self.assertEqual((token, more), ('3', True))
        self.assertEqual(results[0].width, 1920)
        self.assertEqual(request.call_args.args[1]['page'], '2')

    def test_commons_continuation_and_image_types(self):
        data = {'continue': {'gsroffset': 30, 'continue': 'gsroffset||'}, 'query': {'pages': {
            '1': {'title': 'File:Photo.jpg', 'index': 1, 'imageinfo': [{'mime': 'image/jpeg', 'url': 'https://example.org/a.jpg', 'width': 1920, 'height': 1080}]},
            '2': {'title': 'File:Video.webm', 'imageinfo': [{'mime': 'video/webm'}]},
        }}}
        with patch('image_sources._get', return_value=data):
            results, token, more = search('commons', 'mountain', size='Wallpaper')
        self.assertEqual(len(results), 1)
        self.assertEqual(json.loads(token)['gsroffset'], 30)
        self.assertTrue(more)
