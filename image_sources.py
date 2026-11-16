"""Image catalog search adapters using public JSON APIs."""
import json
import urllib.parse
import urllib.request
from bing_images import BingImage as SearchImage

API_SIZES = ('Wallpaper', 'Large', 'Medium', 'Small', '')


def _get(url, params):
    request = urllib.request.Request(url + '?' + urllib.parse.urlencode(params), headers={
        'User-Agent': 'Lingo/1.0 (Linux desktop wallpaper app)', 'Accept': 'application/json',
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if 'error' in data:
        raise RuntimeError(str(data['error']))
    return data


def search(engine, query, *, size='', token=None):
    if engine == 'wallhaven':
        params = {'q': query, 'page': token or '1', 'purity': '100', 'sorting': 'relevance'}
        if size in ('Wallpaper', 'Large'):
            params['atleast'] = '1920x1080' if size == 'Wallpaper' else '1280x720'
        data = _get('https://wallhaven.cc/api/v1/search', params)
        results = [SearchImage(
            title='Wallhaven ' + item['id'], image_url=item['path'],
            thumb_url=item.get('thumbs', {}).get('small', ''), width=item['dimension_x'],
            height=item['dimension_y'], source='wallhaven.cc', page_url=item['url'],
        ) for item in data.get('data', [])]
        page = data.get('meta', {}).get('current_page', int(token or 1))
        return results, str(page + 1), page < data.get('meta', {}).get('last_page', page)
    if engine != 'commons':
        raise ValueError(f'Unknown image catalog: {engine}')
    params = {
        'action': 'query', 'format': 'json', 'generator': 'search', 'gsrsearch': query,
        'gsrnamespace': '6', 'gsrlimit': '30', 'prop': 'imageinfo',
        'iiprop': 'url|size|mime', 'iiurlwidth': '320',
    }
    if token:
        params.update(json.loads(token))
    data = _get('https://commons.wikimedia.org/w/api.php', params)
    results = []
    pages = sorted(data.get('query', {}).get('pages', {}).values(), key=lambda p: p.get('index', 0))
    for page in pages:
        for item in page.get('imageinfo', []):
            if item.get('mime') not in ('image/jpeg', 'image/png', 'image/webp', 'image/tiff'):
                continue
            width, height = item.get('width', 0), item.get('height', 0)
            if size == 'Wallpaper' and (width < 1920 or height < 1080):
                continue
            if size == 'Large' and max(width, height) < 1280:
                continue
            if size == 'Medium' and not 500 <= max(width, height) < 1280:
                continue
            if size == 'Small' and max(width, height) >= 500:
                continue
            results.append(SearchImage(
                title=page['title'].removeprefix('File:'), image_url=item['url'],
                thumb_url=item.get('thumburl', ''), width=width, height=height,
                source='Wikimedia Commons', page_url=item.get('descriptionurl', ''),
            ))
    continuation = data.get('continue')
    return results, json.dumps(continuation) if continuation else None, bool(continuation)
