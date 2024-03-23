import pytest

from url_shortener.validation import (
    MAX_TTL_SECONDS,
    ValidationError,
    random_slug,
    validate_slug,
    validate_target_url,
    validate_ttl,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com/a/b?c=d&e=f#frag",
        "HTTPS://EXAMPLE.COM/Path",
        "https://example.com:8443/x",
        "https://xn--bcher-kva.example/",
        "http://192.0.2.10/",
        "https://[2001:db8::1]/",
        "https://example.com/" + "a" * 2000,
    ],
)
def test_accepts_http_and_https(url):
    assert validate_target_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        42,
        ["https://example.com"],
        "example.com",
        "//example.com/path",
        "/relative/path",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "https://",
        "https:///path-without-host",
        "https://user:secret@example.com/",
        "https://user@example.com/",
        "https://example.com:notaport/",
        "https://example.com/a b",
        " https://example.com",
        "https://example.com/\r\nSet-Cookie: x=1",
        "https://example.com/\tx",
        "https://example.com\\@evil.example/",
        "https://example.com/\x00",
        "https://example.com/" + "a" * 2048,
    ],
)
def test_rejects_everything_else(url):
    with pytest.raises(ValidationError):
        validate_target_url(url)


def test_rejects_links_back_to_the_shortener():
    with pytest.raises(ValidationError, match="point back"):
        validate_target_url("https://Short.Example/abc", own_host="short.example")
    with pytest.raises(ValidationError, match="point back"):
        validate_target_url("http://127.0.0.1:9000/abc", own_host="127.0.0.1:8080")
    assert validate_target_url("https://other.example/", own_host="short.example")


@pytest.mark.parametrize("slug", ["abc", "my-link_2", "A" * 32, "0000000"])
def test_valid_slugs(slug):
    assert validate_slug(slug) == slug


@pytest.mark.parametrize(
    "slug", [None, "", "ab", "A" * 33, "has space", "a/b", "a.b", "ünï", "links", "LINKS", 123, "abc\n"]
)
def test_invalid_slugs(slug):
    with pytest.raises(ValidationError):
        validate_slug(slug)


def test_ttl():
    assert validate_ttl(None) is None
    assert validate_ttl(0) is None
    assert validate_ttl(1) == 1
    assert validate_ttl(MAX_TTL_SECONDS) == MAX_TTL_SECONDS
    for bad in (-1, MAX_TTL_SECONDS + 1, 1.5, "60", True, [60]):
        with pytest.raises(ValidationError):
            validate_ttl(bad)


def test_random_slugs_are_valid_and_vary():
    slugs = {random_slug() for _ in range(200)}
    assert len(slugs) > 190
    assert all(validate_slug(slug) and len(slug) == 7 for slug in slugs)
