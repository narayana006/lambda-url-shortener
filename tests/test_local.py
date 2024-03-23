import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from url_shortener.handler import handle
from url_shortener.local import make_request_handler


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


@pytest.fixture
def server(table, monkeypatch):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_request_handler(handle, table))
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    monkeypatch.setenv("BASE_URL", base)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield base
    httpd.shutdown()
    httpd.server_close()


def test_local_server_round_trip(server):
    status, _, body = call(server, "POST", "/links", {"url": "https://example.com/x", "slug": "local"})
    assert status == 201
    assert json.loads(body)["short_url"] == f"{server}/local"

    status, headers, _ = call(server, "GET", "/local")
    assert (status, headers["location"]) == (302, "https://example.com/x")

    status, _, body = call(server, "GET", "/links/local")
    assert (status, json.loads(body)["clicks"]) == (200, 1)

    assert call(server, "GET", "/missing")[0] == 404
    assert call(server, "POST", "/links", {"url": "ftp://example.com"})[0] == 400
