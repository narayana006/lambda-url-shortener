"""AWS Lambda entry point.

Understands payload format version 2.0, which is what both API Gateway HTTP
APIs and Lambda function URLs send.

Routes:
  POST /links          create a link     body: {"url": ..., "slug": ..., "ttl_seconds": ...}
  GET  /links/{slug}   link details and click count, as JSON
  GET  /{slug}         302 redirect to the target, counting one click

Environment variables:
  TABLE_NAME            DynamoDB table name. Required.
  CREATE_TOKEN          If set, POST /links needs "Authorization: Bearer <token>".
  DEFAULT_TTL_SECONDS   Expiry for links created without ttl_seconds. 0 = never.
  BASE_URL              Prefix for short URLs in responses. Default: https://<request host>.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import time

from .store import LinkStore, SlugTaken
from .validation import (
    ValidationError,
    is_valid_slug,
    random_slug,
    validate_slug,
    validate_target_url,
    validate_ttl,
)

MAX_BODY_BYTES = 4096
SLUG_ATTEMPTS = 5

_default_table = None


def _table():
    global _default_table
    if _default_table is None:
        import boto3

        _default_table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
    return _default_table


def _json(status: int, body: dict, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store", **(headers or {})},
        "body": json.dumps(body),
    }


def _error(status: int, message: str) -> dict:
    return _json(status, {"error": message})


def _headers(event: dict) -> dict:
    return {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}


def _request_host(event: dict) -> str:
    return (event.get("requestContext") or {}).get("domainName") or _headers(event).get("host") or ""


def _base_url(event: dict) -> str:
    configured = os.environ.get("BASE_URL", "").strip()
    return configured.rstrip("/") if configured else f"https://{_request_host(event)}"


def _authorized(event: dict) -> bool:
    token = os.environ.get("CREATE_TOKEN", "")
    if not token:
        return True
    supplied = _headers(event).get("authorization", "")
    return hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode())


def _read_body(event: dict) -> dict:
    raw = event.get("body")
    if raw is None or raw == "":
        raise ValidationError("request body must be a JSON object")
    try:
        data = base64.b64decode(raw, validate=True) if event.get("isBase64Encoded") else raw.encode()
        if len(data) > MAX_BODY_BYTES:
            raise ValidationError(f"request body is larger than {MAX_BODY_BYTES} bytes")
        body = json.loads(data)
    except ValidationError:
        raise
    except ValueError:  # bad base64, bad UTF-8 or bad JSON
        raise ValidationError("request body must be a JSON object") from None
    if not isinstance(body, dict):
        raise ValidationError("request body must be a JSON object")
    return body


def _create(event: dict, store: LinkStore, now: int, slug_factory) -> dict:
    if not _authorized(event):
        return _json(401, {"error": "missing or wrong bearer token"}, {"www-authenticate": "Bearer"})
    try:
        body = _read_body(event)
        unknown = set(body) - {"url", "slug", "ttl_seconds"}
        if unknown:
            raise ValidationError(f"unknown field(s): {', '.join(sorted(unknown))}")
        url = validate_target_url(body.get("url"), own_host=_request_host(event))
        ttl = validate_ttl(body.get("ttl_seconds", int(os.environ.get("DEFAULT_TTL_SECONDS") or 0)))
        custom_slug = validate_slug(body["slug"]) if "slug" in body else None
    except ValidationError as error:
        return _error(400, str(error))
    expires_at = None if ttl is None else now + ttl

    link = None
    if custom_slug is not None:
        try:
            link = store.create(custom_slug, url, now, expires_at)
        except SlugTaken:
            return _error(409, f"slug '{custom_slug}' is already in use")
    else:
        for _ in range(SLUG_ATTEMPTS):
            try:
                link = store.create(slug_factory(), url, now, expires_at)
                break
            except SlugTaken:
                continue
        if link is None:
            return _error(503, "could not find a free slug, please try again")

    short_url = f"{_base_url(event)}/{link.slug}"
    return _json(201, {"short_url": short_url, **link.to_dict()}, {"location": short_url})


def _stats(slug: str, store: LinkStore, now: int) -> dict:
    link = store.get(slug, now) if is_valid_slug(slug) else None
    if link is None:
        return _error(404, "no such link")
    return _json(200, link.to_dict())


def _redirect(slug: str, store: LinkStore, now: int) -> dict:
    url = store.resolve(slug, now) if is_valid_slug(slug) else None
    if url is None:
        return _error(404, "no such link")
    # 302 and no-store so browsers come back each time and every visit is counted.
    return {"statusCode": 302, "headers": {"location": url, "cache-control": "no-store"}, "body": ""}


def handle(event: dict, context=None, *, table=None, now=None, slug_factory=random_slug) -> dict:
    """Route one request. The keyword arguments are for tests and the local server."""
    http = (event.get("requestContext") or {}).get("http") or {}
    method = str(http.get("method", "")).upper()
    path = event.get("rawPath") or http.get("path") or "/"
    segments = [segment for segment in path.split("/") if segment]
    store = LinkStore(table if table is not None else _table())
    now = int(time.time() if now is None else now)

    if segments == ["links"]:
        if method != "POST":
            return _json(405, {"error": "use POST to create a link"}, {"allow": "POST"})
        return _create(event, store, now, slug_factory)
    if len(segments) == 2 and segments[0] == "links":
        if method != "GET":
            return _json(405, {"error": "use GET to read a link"}, {"allow": "GET"})
        return _stats(segments[1], store, now)
    if len(segments) == 1:
        if method != "GET":
            return _json(405, {"error": "use GET to follow a link"}, {"allow": "GET"})
        return _redirect(segments[0], store, now)
    return _error(404, "not found")


def lambda_handler(event, context):
    return handle(event, context)
