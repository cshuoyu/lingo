"""Bounded HTTP transfers for image search, thumbnails and downloads."""
import gzip
import shutil
import subprocess
import urllib.request
import zlib


def fetch_bytes(url: str, *, headers: dict[str, str] | None = None,
                timeout: int = 15, max_bytes: int = 8 * 1024 * 1024) -> bytes:
    headers = headers or {}
    curl = shutil.which('curl')
    if curl:
        # --disable ignores user curlrc options; argv avoids shell interpretation.
        command = [
            curl, '--disable', '--silent', '--show-error', '--location',
            '--compressed', '--fail', '--max-time', str(timeout),
            '--connect-timeout', str(min(timeout, 6)), '--max-redirs', '3',
            '--proto', '=http,https', '--proto-redir', '=http,https',
            '--max-filesize', str(max_bytes),
        ]
        for key, value in headers.items():
            command.extend(['--header', f'{key}: {value}'])
        command.append(url)
        try:
            response = subprocess.run(command, capture_output=True, timeout=timeout + 2)
        except subprocess.TimeoutExpired as e:
            raise OSError('Network request timed out') from e
        if response.returncode:
            raise OSError(response.stderr.decode('utf-8', errors='replace').strip() or 'Network request failed')
        data = response.stdout
    else:
        # Minimal-install fallback. curl is preferred because its total timeout
        # also bounds DNS resolution and it races IPv4/IPv6 connections.
        request = urllib.request.Request(url, headers={**headers, 'Accept-Encoding': 'gzip, deflate'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            encoding = response.headers.get('Content-Encoding', '').lower()
        if encoding == 'gzip' or data.startswith(b'\x1f\x8b'):
            data = gzip.decompress(data)
        elif encoding == 'deflate':
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
    if len(data) > max_bytes:
        raise ValueError(f'Response exceeds the {max_bytes // (1024 * 1024)} MB limit')
    return data
