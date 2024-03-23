import base64
import json
from pathlib import Path

import pytest

from conftest import HOST, NOW
from url_shortener import handler

EVENTS = Path(__file__).parent.parent / "examples" / "events"


def load(name):
    return json.loads((EVENTS / f"{name}.json").read_text())


def test_create_then_redirect_then_stats(api):
    status, body, headers = api.create("https://example.com/a?b=c", slug="my-link")
    assert status == 201
    assert body == {
        "short_url": f"https://{HOST}/my-link",
        "slug": "my-link",
        "url": "https://example.com/a?b=c",
        "clicks": 0,
        "created_at": NOW,
        "expires_at": None,
    }
    assert headers["location"] == f"https://{HOST}/my-link"

    for _ in range(2):
        status, body, headers = api.request("GET", "/my-link")
        assert (status, body) == (302, None)
        assert headers["location"] == "https://example.com/a?b=c"
        assert headers["cache-control"] == "no-store"

    status, body, _ = api.request("GET", "/links/my-link")
    assert status == 200
    assert body["clicks"] == 2 and body["url"] == "https://example.com/a?b=c"

    # reading stats does not count as a click
    assert api.request("GET", "/links/my-link")[1]["clicks"] == 2


def test_generated_slug(api):
    status, body, _ = api.create()
    assert status == 201
    assert len(body["slug"]) == 7 and body["slug"].isalnum()
    assert api.request("GET", "/" + body["slug"])[0] == 302


def test_existing_slug_is_refused_and_not_overwritten(api):
    assert api.create("https://first.example/", slug="taken")[0] == 201
    status, body, _ = api.create("https://second.example/", slug="taken")
    assert (status, body) == (409, {"error": "slug 'taken' is already in use"})
    assert api.request("GET", "/taken")[2]["location"] == "https://first.example/"


def test_generated_slug_collision_retries(api):
    api.create(slug="aaaaaaa")
    api.slugs = iter(["aaaaaaa", "aaaaaaa", "bbbbbbb"])
    status, body, _ = api.create("https://other.example/")
    assert (status, body["slug"]) == (201, "bbbbbbb")
    assert api.request("GET", "/links/aaaaaaa")[1]["url"] == "https://example.com/page"


def test_gives_up_after_repeated_collisions(api):
    api.create(slug="aaaaaaa")
    api.slugs = iter(["aaaaaaa"] * 5)
    status, body, _ = api.create()
    assert status == 503 and "free slug" in body["error"]


@pytest.mark.parametrize(
    "body, fragment",
    [
        ({}, "'url' is required"),
        ({"url": "ftp://example.com/x"}, "http:// or https://"),
        ({"url": "javascript:alert(1)"}, "http:// or https://"),
        ({"url": "https://user:pw@example.com/"}, "user name or password"),
        ({"url": f"https://{HOST}/loop"}, "point back"),
        ({"url": "https://example.com", "slug": "no"}, "'slug' must be"),
        ({"url": "https://example.com", "slug": "links"}, "reserved"),
        ({"url": "https://example.com", "ttl_seconds": -5}, "ttl_seconds"),
        ({"url": "https://example.com", "ttl_seconds": "60"}, "ttl_seconds"),
        ({"url": "https://example.com", "admin": True}, "unknown field(s): admin"),
    ],
)
def test_bad_requests(api, body, fragment):
    status, data, _ = api.request("POST", "/links", body)
    assert status == 400
    assert fragment in data["error"]
    assert api.table.scan()["Count"] == 0


@pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]", '"https://example.com"', "{" + " " * 5000 + "}"])
def test_bad_bodies(api, raw):
    status, data, _ = api.request("POST", "/links", raw_body=raw)
    assert status == 400 and "request body" in data["error"]


def test_expiring_link(api):
    status, body, _ = api.create(slug="temp", ttl_seconds=60)
    assert (status, body["expires_at"]) == (201, NOW + 60)
    api.now = NOW + 59
    assert api.request("GET", "/temp")[0] == 302
    api.now = NOW + 60
    assert api.request("GET", "/temp") [0] == 404
    assert api.request("GET", "/links/temp")[0] == 404
    # and the slug is free again
    assert api.create("https://new.example/", slug="temp")[0] == 201


def test_default_ttl_from_environment(api, monkeypatch):
    monkeypatch.setenv("DEFAULT_TTL_SECONDS", "3600")
    assert api.create(slug="default")[1]["expires_at"] == NOW + 3600
    assert api.create(slug="explicit", ttl_seconds=10)[1]["expires_at"] == NOW + 10
    assert api.create(slug="forever", ttl_seconds=0)[1]["expires_at"] is None


def test_unknown_and_malformed_slugs_are_404(api):
    for path in ("/nope", "/links/nope", "/a.b", "/%2e%2e", "/x", "/abc%0A"):
        status, body, _ = api.request("GET", path)
        assert (status, body) == (404, {"error": "no such link"}), path
    assert api.request("GET", "/")[0] == 404
    assert api.request("GET", "/a/b/c")[0] == 404
    assert api.table.scan()["Count"] == 0


def test_wrong_methods(api):
    api.create(slug="abc")
    assert api.request("POST", "/abc", {})[0] == 405
    assert api.request("DELETE", "/links/abc")[0] == 405
    assert api.request("PUT", "/links", {"url": "https://example.com"})[0] == 405
    assert api.request("GET", "/links")[0] == 405
    assert api.request("GET", "/links/abc")[1]["clicks"] == 0


def test_create_token(api, monkeypatch):
    monkeypatch.setenv("CREATE_TOKEN", "s3cret-for-tests")
    body = {"url": "https://example.com", "slug": "abc"}
    status, _, headers = api.request("POST", "/links", body)
    assert status == 401 and headers["www-authenticate"] == "Bearer"
    assert api.request("POST", "/links", body, {"Authorization": "Bearer wrong"})[0] == 401
    assert api.request("POST", "/links", body, {"Authorization": "s3cret-for-tests"})[0] == 401
    assert api.table.scan()["Count"] == 0
    assert api.request("POST", "/links", body, {"Authorization": "Bearer s3cret-for-tests"})[0] == 201
    # following and reading links stays public
    assert api.request("GET", "/abc")[0] == 302
    assert api.request("GET", "/links/abc")[0] == 200


def test_base_url_override(api, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://sho.rt/")
    assert api.create(slug="abc")[1]["short_url"] == "https://sho.rt/abc"


def test_http_api_sample_events(table):
    created = handler.handle(load("create-link.http-api"), None, table=table, now=NOW)
    assert created["statusCode"] == 201
    assert json.loads(created["body"])["short_url"] == f"https://{HOST}/lambda-docs"
    redirect = handler.handle(load("redirect.http-api"), None, table=table, now=NOW)
    assert redirect["statusCode"] == 302
    assert redirect["headers"]["location"] == "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html"
    stats = handler.handle(load("stats.http-api"), None, table=table, now=NOW)
    assert json.loads(stats["body"])["clicks"] == 1
    expiring = handler.handle(load("create-expiring-link.http-api"), None, table=table, now=NOW)
    assert json.loads(expiring["body"])["expires_at"] == NOW + 3600
    assert handler.handle(load("create-bad-scheme.http-api"), None, table=table, now=NOW)["statusCode"] == 400


def test_function_url_sample_event_with_base64_body(table):
    event = load("create-link.function-url")
    assert event["isBase64Encoded"] is True
    response = handler.handle(event, None, table=table, now=NOW)
    assert response["statusCode"] == 201
    assert json.loads(response["body"])["short_url"] == f"https://{event['requestContext']['domainName']}/from-furl"

    event["body"] = "!!! not base64 !!!"
    assert handler.handle(event, None, table=table, now=NOW)["statusCode"] == 400
    event["body"] = base64.b64encode(b"\xff\xfe").decode()
    assert handler.handle(event, None, table=table, now=NOW)["statusCode"] == 400


def test_lambda_handler_builds_table_from_environment(table, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", "links")
    response = handler.lambda_handler(load("create-link.http-api"), None)
    assert response["statusCode"] == 201
    assert table.get_item(Key={"slug": "lambda-docs"})["Item"]["clicks"] == 0
