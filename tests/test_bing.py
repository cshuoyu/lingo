import gzip
import html
import json
import unittest
import zlib
from unittest.mock import patch, MagicMock
from urllib.parse import parse_qs, urlparse
import bing_images


def tile(name='photo', width=1920, height=1080):
    metadata = html.escape(json.dumps({'murl': f'https://example.org/{name}.jpg', 't': name, 'ow': width, 'oh': height}))
    return f'<a m="{metadata}" class="tile iusc extra"></a>'


class BingTests(unittest.TestCase):
    def test_attribute_order_quotes_classes_and_bad_dimensions(self):
        metadata = html.escape(json.dumps({'murl': 'https://example.org/a.jpg', 'ow': 'unknown', 't': 'A & B'}), quote=True)
        body = f"<a m='{metadata}' class='tile iusc extra'></a>"
        results = bing_images.parse_results(body * 2 + '<a class="iusc" m="broken">')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].width, 0)
        self.assertEqual(results[0].title, 'A & B')

    def test_request_preserves_query_and_omits_broken_server_filter(self):
        response = MagicMock()
        response.headers = {}
        response.__enter__.return_value = response
        response.read.return_value = tile().encode()
        with patch('http_client.shutil.which', return_value=None), patch('urllib.request.urlopen', return_value=response) as request:
            results, more = bing_images.search('C++ & mountains')
        url = request.call_args.args[0].full_url
        self.assertEqual(urlparse(url).path, '/images/async')
        self.assertEqual(urlparse(url).hostname, 'www.bing.com')
        params = parse_qs(urlparse(url).query)
        self.assertEqual(params['q'], ['C++ & mountains'])
        self.assertEqual(params['first'], ['0'])
        self.assertNotIn('qft', params)
        self.assertNotIn('safeSearch', params)
        self.assertEqual(len(results), 1)

    def test_filtered_page_retains_source_offset(self):
        body = tile('small', 300, 200) + tile('wallpaper') + tile('medium', 800, 600)
        with patch('bing_images._fetch_html', return_value=body):
            results, more = bing_images.search('mountains', start=35)
        self.assertEqual([image.title for image in results], ['wallpaper'])
        self.assertEqual(results.next_start, 38)
        self.assertEqual(results.scanned_count, 3)
        self.assertTrue(more)

    def test_page_without_size_matches_can_still_paginate(self):
        with patch('bing_images._fetch_html', return_value=tile('small', 300, 200)):
            results, more = bing_images.search('mountains')
        self.assertEqual(results, [])
        self.assertEqual(results.next_start, 1)
        self.assertTrue(more)

    def test_size_buckets(self):
        body = tile('small', 300, 200) + tile('medium', 800, 600) + tile('large', 1500, 1000) + tile('wallpaper')
        for size, expected in [('small', ['small']), ('medium', ['medium']), ('large', ['large', 'wallpaper']), ('wallpaper', ['wallpaper']), ('', ['small', 'medium', 'large', 'wallpaper'])]:
            with self.subTest(size=size), patch('bing_images._fetch_html', return_value=body):
                results, _ = bing_images.search('mountains', size=size)
                self.assertEqual([image.title for image in results], expected)

    def test_challenge_is_reported(self):
        with patch('bing_images._fetch_html', return_value='<form id="challenge-form">captcha</form>'):
            with self.assertRaisesRegex(RuntimeError, 'verification'):
                bing_images.search('mountains')

    def test_empty_async_falls_back_to_search_page(self):
        with patch('bing_images._fetch_html', side_effect=['', tile()]) as request:
            results, more = bing_images.search('mountains')
        self.assertEqual(len(results), 1)
        self.assertTrue(more)
        self.assertEqual(urlparse(request.call_args.args[0]).path, '/images/search')
        self.assertNotIn('qft=', request.call_args.args[0])

    def test_script_only_response_is_not_reported_as_zero_results(self):
        with patch('bing_images._fetch_html', return_value='<script>/* no results in telemetry */</script>'):
            with self.assertRaisesRegex(RuntimeError, 'unsupported'):
                bing_images.search('mountains')

    def test_genuine_no_results_page(self):
        with patch('bing_images._fetch_html', return_value='<div id="nr_indicator">No results</div>'):
            results, more = bing_images.search('query')
        self.assertEqual(results, [])
        self.assertFalse(more)

    def test_compressed_responses(self):
        content = tile().encode()
        for encoding, data in [('gzip', gzip.compress(content)), ('deflate', zlib.compress(content))]:
            response = MagicMock()
            response.headers = {'Content-Encoding': encoding}
            response.__enter__.return_value = response
            response.read.return_value = data
            with self.subTest(encoding=encoding), patch('http_client.shutil.which', return_value=None), patch('urllib.request.urlopen', return_value=response):
                self.assertEqual(bing_images._fetch_html('https://www.bing.com/images/async'), content.decode())

    def test_dimension_fallback_from_link(self):
        metadata = html.escape(json.dumps({'murl': 'https://example.org/a.jpg'}))
        result = bing_images.parse_results(f'<a class="iusc" m="{metadata}" href="?expw=1920&amp;exph=1080">')[0]
        self.assertEqual((result.width, result.height), (1920, 1080))

    def test_curl_bounds_total_request_and_reports_failure(self):
        response = MagicMock(returncode=28, stderr=b'Operation timed out')
        with patch('http_client.shutil.which', return_value='/usr/bin/curl'), patch('http_client.subprocess.run', return_value=response) as run:
            with self.assertRaisesRegex(OSError, 'timed out'):
                bing_images._fetch_html('https://www.bing.com/images/async?q=cat')
        self.assertIn('--max-time', run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs['timeout'], bing_images.TIMEOUT + 2)

    def test_curl_does_not_invoke_shell(self):
        response = MagicMock(returncode=0, stdout=tile().encode())
        with patch('http_client.shutil.which', return_value='/usr/bin/curl'), patch('http_client.subprocess.run', return_value=response) as run:
            self.assertIn('iusc', bing_images._fetch_html('https://www.bing.com/images/async?q=C%2B%2B'))
        self.assertIsInstance(run.call_args.args[0], list)
        self.assertNotIn('shell', run.call_args.kwargs)
