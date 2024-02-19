"""Run the handler behind a plain local HTTP server, with no AWS account.

    pip install "lambda-url-shortener[local]"
    url-shortener-local --port 8080

Each HTTP request is turned into the event a Lambda function URL would send
and passed to the real handler. Storage is moto's in-memory DynamoDB mock, so
all links are gone when the server stops. For development only.
"""

from __future__ import annotations

import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TABLE_NAME = "links-local"

FAKE_AWS_ENV = {
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_SHARED_CREDENTIALS_FILE": "/nonexistent/credentials",
    "AWS_CONFIG_FILE": "/nonexistent/config",
}


def make_event(method: str, path: str, body: str | None = None, headers: dict | None = None,
               host: str = "abcdefghij.lambda-url.us-east-1.on.aws") -> dict:
    """Build a payload-format-2.0 event like the one a function URL sends."""
    parts = urlsplit(path)
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    lowered.setdefault("host", host)
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": parts.path,
        "rawQueryString": parts.query,
        "headers": lowered,
        "requestContext": {
            "accountId": "anonymous",
            "apiId": host.split(".")[0],
            "domainName": host,
            "domainPrefix": host.split(".")[0],
            "http": {
                "method": method,
                "path": parts.path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": lowered.get("user-agent", ""),
            },
            "requestId": "00000000-0000-0000-0000-000000000000",
            "routeKey": "$default",
            "stage": "$default",
            "time": "01/Jan/2025:00:00:00 +0000",
            "timeEpoch": 1735689600000,
        },
        "body": body,
        "isBase64Encoded": False,
    }


def create_table(dynamodb_resource, name: str = TABLE_NAME):
    """Create the same table the SAM template defines (key schema only)."""
    return dynamodb_resource.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "slug", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "slug", "KeyType": "HASH"}],
    )


def make_request_handler(handle, table):
    class RequestHandler(BaseHTTPRequestHandler):
        def _dispatch(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", "replace") if length else None
            host = self.headers.get("Host", "localhost")
            event = make_event(self.command, self.path, body, dict(self.headers.items()), host)
            result = handle(event, None, table=table)
            payload = (result.get("body") or "").encode()
            self.send_response(result["statusCode"])
            for name, value in result.get("headers", {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _dispatch

        def log_message(self, fmt, *args):
            sys.stderr.write(fmt % args + "\n")

    return RequestHandler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="url-shortener-local",
        description="Serve the URL shortener on 127.0.0.1 with in-memory storage (moto). "
        "For trying it out; nothing is deployed and nothing is kept.",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--create-token", default="", help="require this bearer token on POST /links")
    args = parser.parse_args(argv)

    # Fake credentials before boto3 is imported, so nothing can reach a real account.
    os.environ.update(FAKE_AWS_ENV)
    os.environ.pop("AWS_PROFILE", None)
    os.environ["CREATE_TOKEN"] = args.create_token
    try:
        import boto3
        from moto import mock_aws
    except ImportError:
        print('url-shortener-local needs moto: pip install "lambda-url-shortener[local]"', file=sys.stderr)
        return 2
    from .handler import handle

    with mock_aws():
        table = create_table(boto3.resource("dynamodb"))
        server = ThreadingHTTPServer(("127.0.0.1", args.port), make_request_handler(handle, table))
        os.environ["BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
        print(f"url-shortener-local listening on http://127.0.0.1:{server.server_address[1]} "
              "(in-memory storage, Ctrl-C to stop)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
