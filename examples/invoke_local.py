"""Feed the sample events in examples/events/ to the real handler, with no AWS account.

    pip install -e ".[dev]"
    python examples/invoke_local.py

The handler and its DynamoDB calls are real; DynamoDB itself is moto's
in-memory mock. Nothing is deployed and nothing leaves this machine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from url_shortener.local import FAKE_AWS_ENV, create_table

# Fake credentials before boto3 is imported, so nothing can reach a real account.
os.environ.update(FAKE_AWS_ENV)
os.environ.pop("AWS_PROFILE", None)

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

from url_shortener.handler import handle  # noqa: E402

EVENTS = Path(__file__).resolve().parent / "events"

SEQUENCE = [
    "create-link.http-api",
    "create-link.http-api",  # same slug again: must be refused
    "redirect.http-api",
    "redirect.http-api",
    "stats.http-api",
    "create-expiring-link.http-api",
    "create-bad-scheme.http-api",
    "create-link.function-url",
]


def main():
    with mock_aws():
        table = create_table(boto3.resource("dynamodb"), "links")
        for name in SEQUENCE:
            event = json.loads((EVENTS / f"{name}.json").read_text())
            http = event["requestContext"]["http"]
            response = handle(event, None, table=table)
            print(f"$ {name}.json   ({http['method']} {http['path']})")
            print(f"  {response['statusCode']}", end="")
            if "location" in response["headers"]:
                print(f"  location: {response['headers']['location']}", end="")
            print()
            if response["body"]:
                print(f"  {response['body']}")
            print()


if __name__ == "__main__":
    main()
