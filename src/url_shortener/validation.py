"""Input checks for target URLs, slugs and expiry times."""

from __future__ import annotations

import re
import secrets
import string
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
MAX_TTL_SECONDS = 10 * 365 * 24 * 3600
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
# Path segments the API uses itself; they can never be slugs.
RESERVED_SLUGS = frozenset({"links"})
SLUG_ALPHABET = string.ascii_letters + string.digits
GENERATED_SLUG_LENGTH = 7


class ValidationError(ValueError):
    """The request is well-formed JSON but a value in it is not acceptable."""


def validate_target_url(url, own_host: str | None = None) -> str:
    """Return the URL unchanged if it is an acceptable redirect target."""
    if not isinstance(url, str) or not url:
        raise ValidationError("'url' is required and must be a string")
    if len(url) > MAX_URL_LENGTH:
        raise ValidationError(f"'url' is longer than {MAX_URL_LENGTH} characters")
    # No spaces, control characters (this also rules out header injection through
    # CR/LF) or backslashes, which browsers may read as forward slashes.
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F or ch == "\\" for ch in url):
        raise ValidationError("'url' must not contain spaces, control characters or backslashes")
    try:
        parts = urlsplit(url)
        parts.port  # raises ValueError for a malformed port
    except ValueError:
        raise ValidationError("'url' is not a valid URL") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise ValidationError("'url' must start with http:// or https://")
    if not parts.hostname:
        raise ValidationError("'url' must include a host name")
    if parts.username is not None or parts.password is not None:
        raise ValidationError("'url' must not contain a user name or password")
    if own_host and parts.hostname.lower() == own_host.lower().split(":")[0]:
        raise ValidationError("'url' must not point back at this shortener")
    return url


def validate_slug(slug) -> str:
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
        raise ValidationError("'slug' must be 3 to 32 characters from A-Z, a-z, 0-9, '_' and '-'")
    if slug.lower() in RESERVED_SLUGS:
        raise ValidationError(f"'{slug}' is reserved and cannot be used as a slug")
    return slug


def is_valid_slug(slug) -> bool:
    try:
        validate_slug(slug)
    except ValidationError:
        return False
    return True


def validate_ttl(ttl) -> int | None:
    """None or 0 means the link never expires."""
    if ttl is None or ttl == 0:
        return None
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 0 < ttl <= MAX_TTL_SECONDS:
        raise ValidationError(f"'ttl_seconds' must be a whole number from 1 to {MAX_TTL_SECONDS}")
    return ttl


def random_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(GENERATED_SLUG_LENGTH))
