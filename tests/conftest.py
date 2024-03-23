import json
import os

# Set before boto3 is imported anywhere, so no test can reach a real AWS account.
_FAKE_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_SECURITY_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/credentials",
    "AWS_CONFIG_FILE": "/nonexistent/config",
}
os.environ.update(_FAKE_ENV)
os.environ.pop("AWS_PROFILE", None)

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402

from url_shortener import handler  # noqa: E402
from url_shortener.local import create_table, make_event  # noqa: E402

NOW = 1_750_000_000
HOST = "a1b2c3d4e5.execute-api.us-east-1.amazonaws.com"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for key in ("TABLE_NAME", "CREATE_TOKEN", "DEFAULT_TTL_SECONDS", "BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(handler, "_default_table", None)


@pytest.fixture
def table():
    with mock_aws():
        create_table(boto3.resource("dynamodb"), "links")
        yield boto3.resource("dynamodb").Table("links")


class Api:
    """Calls the handler the way API Gateway would and decodes the response."""

    def __init__(self, table):
        self.table = table
        self.now = NOW
        self.slugs = None  # optional iterator of slugs to hand out instead of random ones

    def request(self, method, path, body=None, headers=None, raw_body=None):
        if body is not None:
            raw_body = json.dumps(body)
        event = make_event(method, path, raw_body, headers, host=HOST)
        kwargs = {"table": self.table, "now": self.now}
        if self.slugs is not None:
            kwargs["slug_factory"] = lambda: next(self.slugs)
        response = handler.handle(event, None, **kwargs)
        data = json.loads(response["body"]) if response["body"] else None
        return response["statusCode"], data, response["headers"]

    def create(self, url="https://example.com/page", **fields):
        return self.request("POST", "/links", {"url": url, **fields})


@pytest.fixture
def api(table):
    return Api(table)
