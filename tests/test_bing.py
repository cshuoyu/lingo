import html
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlparse
import bing_images


class BingTests(unittest.TestCase):
    def test_attribute_order_quotes_classes_and_bad_dimensions(self):
        metadata = html.escape(json.dumps({'murl': 'https://example.org/a.jpg', 'ow': 'unknown', 't': 'A & B'}), quote=True)
        body = f"<a m='{metadata}' class='tile iusc extra'></a>"
        results = bing_images.parse_results(body * 2 + '<a class="iusc" m="broken">')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].width, 0)
        self.assertEqual(results[0].title, 'A & B')

    def test_request_preserves_query_and_filter(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'no results'
        with patch('urllib.request.urlopen', return_value=response) as request:
            self.assertEqual(bing_images.search('C++ & mountains'), ([], False))
        url = request.call_args_list[0].args[0].full_url
        self.assertEqual(urlparse(url).path, '/images/async')
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params['q'], ['C++ & mountains'])
        self.assertEqual(params['qft'], ['filterui:imagesize-wallpaper'])

    def test_challenge_is_reported(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'<form id="challenge-form">captcha</form>'
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'verification'):
                bing_images.search('mountains')

    def test_empty_async_falls_back_to_search_page(self):
        response = MagicMock()
        metadata = html.escape(json.dumps({'murl': 'https://example.org/a.jpg'}))
        response.__enter__.return_value.read.side_effect = [b'', f'<a class="iusc" m="{metadata}" href="?expw=1920&amp;exph=1080">'.encode()]
        with patch('urllib.request.urlopen', return_value=response) as request:
            results, more = bing_images.search('mountains')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].width, 1920)
        self.assertTrue(more)
        self.assertEqual(urlparse(request.call_args.args[0].full_url).path, '/images/search')
