"""DynamoDB access. Three operations, each a single API call.

Table layout: partition key `slug` (string). Other attributes: `target_url`,
`clicks`, `created_at` and, for links that expire, `expires_at` (Unix seconds),
which is also the table's TTL attribute.

DynamoDB's TTL removes expired items some time after they expire, not at that
exact moment, so every read here also compares `expires_at` with the clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from botocore.exceptions import ClientError


class SlugTaken(Exception):
    """A live link already uses this slug."""


@dataclass(frozen=True)
class Link:
    slug: str
    url: str
    clicks: int
    created_at: int
    expires_at: int | None

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "url": self.url,
            "clicks": self.clicks,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


def _is_condition_failure(error: ClientError) -> bool:
    return error.response["Error"]["Code"] == "ConditionalCheckFailedException"


def _to_link(item: dict) -> Link:
    expires_at = item.get("expires_at")
    return Link(
        slug=item["slug"],
        url=item["target_url"],
        clicks=int(item.get("clicks", 0)),
        created_at=int(item["created_at"]),
        expires_at=None if expires_at is None else int(expires_at),
    )


class LinkStore:
    """Takes a boto3 Table resource so tests can pass a moto-backed one."""

    def __init__(self, table) -> None:
        self.table = table

    def create(self, slug: str, url: str, now: int, expires_at: int | None) -> Link:
        """Write a new link (PutItem). Never overwrites a live link.

        The condition makes the write fail if the slug exists, unless the
        existing item has already expired and is only waiting for TTL cleanup.
        """
        item = {"slug": slug, "target_url": url, "clicks": 0, "created_at": now}
        if expires_at is not None:
            item["expires_at"] = expires_at
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(#slug) OR #expires <= :now",
                ExpressionAttributeNames={"#slug": "slug", "#expires": "expires_at"},
                ExpressionAttributeValues={":now": now},
            )
        except ClientError as error:
            if _is_condition_failure(error):
                raise SlugTaken(slug) from None
            raise
        return _to_link(item)

    def resolve(self, slug: str, now: int) -> str | None:
        """Count a click and return the target URL (UpdateItem), or None.

        The increment is atomic and conditional, so a missing or expired slug
        is neither created nor counted.
        """
        try:
            response = self.table.update_item(
                Key={"slug": slug},
                UpdateExpression="ADD #clicks :one",
                ConditionExpression="attribute_exists(#slug) AND "
                "(attribute_not_exists(#expires) OR #expires > :now)",
                ExpressionAttributeNames={"#slug": "slug", "#expires": "expires_at", "#clicks": "clicks"},
                ExpressionAttributeValues={":one": 1, ":now": now},
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if _is_condition_failure(error):
                return None
            raise
        return response["Attributes"]["target_url"]

    def get(self, slug: str, now: int) -> Link | None:
        """Read a link without counting a click (GetItem)."""
        item = self.table.get_item(Key={"slug": slug}).get("Item")
        if item is None:
            return None
        link = _to_link(item)
        if link.expires_at is not None and link.expires_at <= now:
            return None
        return link
