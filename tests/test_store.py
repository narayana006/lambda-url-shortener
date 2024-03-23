import pytest

from conftest import NOW
from url_shortener.store import LinkStore, SlugTaken


@pytest.fixture
def store(table):
    return LinkStore(table)


def test_create_and_get(store):
    link = store.create("abc", "https://example.com/", NOW, None)
    assert link.to_dict() == {
        "slug": "abc",
        "url": "https://example.com/",
        "clicks": 0,
        "created_at": NOW,
        "expires_at": None,
    }
    assert store.get("abc", NOW) == link
    assert store.get("missing", NOW) is None


def test_create_never_overwrites_a_live_link(store, table):
    store.create("abc", "https://first.example/", NOW, None)
    store.resolve("abc", NOW)
    with pytest.raises(SlugTaken):
        store.create("abc", "https://second.example/", NOW + 10, None)
    item = table.get_item(Key={"slug": "abc"})["Item"]
    assert item["target_url"] == "https://first.example/"
    assert item["clicks"] == 1

    store.create("temp", "https://first.example/", NOW, NOW + 60)
    with pytest.raises(SlugTaken):
        store.create("temp", "https://second.example/", NOW + 59, None)


def test_expired_slug_can_be_reused_before_ttl_cleanup(store, table):
    store.create("temp", "https://old.example/", NOW, NOW + 60)
    store.resolve("temp", NOW)
    # The old item is still physically in the table (DynamoDB TTL deletes later).
    assert table.get_item(Key={"slug": "temp"})["Item"]["target_url"] == "https://old.example/"
    link = store.create("temp", "https://new.example/", NOW + 60, None)
    assert (link.url, link.clicks, link.expires_at) == ("https://new.example/", 0, None)
    assert store.get("temp", NOW + 61).url == "https://new.example/"


def test_resolve_counts_clicks(store):
    store.create("abc", "https://example.com/", NOW, None)
    for _ in range(3):
        assert store.resolve("abc", NOW) == "https://example.com/"
    assert store.get("abc", NOW).clicks == 3


def test_resolve_missing_slug_creates_nothing(store, table):
    assert store.resolve("ghost", NOW) is None
    assert table.scan()["Count"] == 0


def test_expiry_is_enforced_on_read_even_if_item_still_exists(store, table):
    store.create("temp", "https://example.com/", NOW, NOW + 60)
    assert store.resolve("temp", NOW + 59) == "https://example.com/"
    assert store.resolve("temp", NOW + 60) is None
    assert store.get("temp", NOW + 59).expires_at == NOW + 60
    assert store.get("temp", NOW + 60) is None
    assert table.get_item(Key={"slug": "temp"})["Item"]["clicks"] == 1  # the expired hit was not counted


def test_other_dynamodb_errors_are_not_swallowed(table):
    from botocore.exceptions import ClientError
    import boto3

    missing = LinkStore(boto3.resource("dynamodb").Table("no-such-table"))
    for call in (
        lambda: missing.create("abc", "https://example.com/", NOW, None),
        lambda: missing.resolve("abc", NOW),
    ):
        with pytest.raises(ClientError) as info:
            call()
        assert info.value.response["Error"]["Code"] == "ResourceNotFoundException"
