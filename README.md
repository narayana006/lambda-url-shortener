# lambda-url-shortener

A minimal serverless URL shortener on AWS Lambda and DynamoDB, written as a small reference project you can read in one sitting: one handler, one table, tests that run without AWS, and an IAM policy with three actions.

**Status:** the handler (create, redirect, click counts, expiry), the DynamoDB layer and a local development server all work and are covered by 94 tests that use [moto](https://github.com/getmoto/moto) instead of AWS. The SAM template is written and passes `cfn-lint`, but **it has not been deployed to a real AWS account yet**.

> **No real access control and no abuse protection.** By default anyone who can reach the URL can create links, and anyone can follow them and read their click counts. The only protection included is an optional shared bearer token for link creation. There is no rate limiting, no per-user accounts, no malware or phishing checks on target URLs, and no way to delete a link through the API. Do not put this on the public internet as-is and expect it to stay clean. See [Security](#security-read-this-before-deploying).

## Try it locally (no AWS account)

```bash
git clone https://github.com/narayana006/lambda-url-shortener
cd lambda-url-shortener
pip install -e ".[local]"
url-shortener-local --port 8080
```

This runs the real Lambda handler behind a plain HTTP server on `127.0.0.1`. Storage is moto's in-memory DynamoDB mock, so links disappear when you stop it. In another terminal (real output from a run of exactly these commands):

```console
$ curl -s -X POST http://127.0.0.1:8080/links -d '{"url": "https://example.com/some/long/path?ref=readme", "slug": "demo"}'
{"short_url": "http://127.0.0.1:8080/demo", "slug": "demo", "url": "https://example.com/some/long/path?ref=readme", "clicks": 0, "created_at": 1794320808, "expires_at": null}

$ curl -s -X POST http://127.0.0.1:8080/links -d '{"url": "https://example.org/", "slug": "demo"}'
{"error": "slug 'demo' is already in use"}

$ curl -s -i http://127.0.0.1:8080/demo
HTTP/1.0 302 Found
Server: BaseHTTP/0.6 Python/3.11.15
Date: Tue, 10 Nov 2026 14:26:48 GMT
location: https://example.com/some/long/path?ref=readme
cache-control: no-store
Content-Length: 0

$ curl -s -o /dev/null http://127.0.0.1:8080/demo
$ curl -s http://127.0.0.1:8080/links/demo
{"slug": "demo", "url": "https://example.com/some/long/path?ref=readme", "clicks": 2, "created_at": 1794320808, "expires_at": null}

$ curl -s -X POST http://127.0.0.1:8080/links -d '{"url": "https://example.com/", "ttl_seconds": 3600}'
{"short_url": "http://127.0.0.1:8080/hLglQAo", "slug": "hLglQAo", "url": "https://example.com/", "clicks": 0, "created_at": 1794320808, "expires_at": 1794324408}

$ curl -s -X POST http://127.0.0.1:8080/links -d '{"url": "javascript:alert(1)"}'
{"error": "'url' must start with http:// or https://"}
```

Generated slugs are random, so yours will differ from `hLglQAo`.

`url-shortener-local --create-token SECRET` turns on the bearer-token check for `POST /links`.

If you only want the package: `pip install "lambda-url-shortener[local] @ git+https://github.com/narayana006/lambda-url-shortener"` (or `pip install git+https://github.com/narayana006/lambda-url-shortener` without the local server's moto dependency).

## API

All JSON. Errors look like `{"error": "..."}`.

### `POST /links` — create a link

```json
{ "url": "https://example.com/page", "slug": "my-link", "ttl_seconds": 86400 }
```

| Field | Required | Rules |
| --- | --- | --- |
| `url` | yes | `http://` or `https://` only, with a host name; at most 2048 characters; no spaces, control characters or backslashes; no `user:password@`; must not point at the shortener's own host. |
| `slug` | no | 3 to 32 characters from `A-Z a-z 0-9 _ -`. `links` is reserved. If omitted, a random 7-character slug is generated. |
| `ttl_seconds` | no | Whole number from 1 to 315360000 (10 years). `0` or omitted means the deployment default, which is "never expires" unless you set `DefaultTtlSeconds`. |

Responses: `201` with the link (and a `location` header holding the short URL), `400` for invalid input or unknown fields, `401` if a create token is configured and the request does not carry it, `409` if the slug is already in use, `503` if five random slugs in a row were all taken.

A slug is never overwritten: the write is a DynamoDB conditional `PutItem`, so two simultaneous requests for the same slug cannot both succeed. The one exception is a slug whose link has already expired; that slug can be claimed again.

### `GET /{slug}` — follow a link

`302` with a `location` header, and the link's click count goes up by one. `404` if the slug does not exist or has expired. The response is `cache-control: no-store` and deliberately not a `301`, so browsers ask again each time and every visit is counted.

Counting and lookup are one conditional `UpdateItem` (`ADD clicks 1`), so concurrent visits do not lose counts.

### `GET /links/{slug}` — link details

`200` with `slug`, `url`, `clicks`, `created_at`, `expires_at` (Unix seconds, or `null`). Does not count as a click. `404` if missing or expired. This is public: anyone who knows a slug can see where it points and how often it was used.

Any other method on these paths gets `405`.

## Running the handler on sample events

`examples/events/` contains event payloads in the shape API Gateway HTTP APIs and Lambda function URLs send (payload format 2.0; the function URL sample has a base64-encoded body). `examples/invoke_local.py` feeds them to the handler against moto:

```bash
pip install -e ".[dev]"
python examples/invoke_local.py
```

Real output:

```text
$ create-link.http-api.json   (POST /links)
  201  location: https://a1b2c3d4e5.execute-api.us-east-1.amazonaws.com/lambda-docs
  {"short_url": "https://a1b2c3d4e5.execute-api.us-east-1.amazonaws.com/lambda-docs", "slug": "lambda-docs", "url": "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html", "clicks": 0, "created_at": 1794320804, "expires_at": null}

$ create-link.http-api.json   (POST /links)
  409
  {"error": "slug 'lambda-docs' is already in use"}

$ redirect.http-api.json   (GET /lambda-docs)
  302  location: https://docs.aws.amazon.com/lambda/latest/dg/welcome.html

$ redirect.http-api.json   (GET /lambda-docs)
  302  location: https://docs.aws.amazon.com/lambda/latest/dg/welcome.html

$ stats.http-api.json   (GET /links/lambda-docs)
  200
  {"slug": "lambda-docs", "url": "https://docs.aws.amazon.com/lambda/latest/dg/welcome.html", "clicks": 2, "created_at": 1794320804, "expires_at": null}

$ create-expiring-link.http-api.json   (POST /links)
  201  location: https://a1b2c3d4e5.execute-api.us-east-1.amazonaws.com/zStLbkz
  {"short_url": "https://a1b2c3d4e5.execute-api.us-east-1.amazonaws.com/zStLbkz", "slug": "zStLbkz", "url": "https://example.com/sale?utm_source=newsletter", "clicks": 0, "created_at": 1794320804, "expires_at": 1794324404}

$ create-bad-scheme.http-api.json   (POST /links)
  400
  {"error": "'url' must start with http:// or https://"}

$ create-link.function-url.json   (POST /links)
  201  location: https://abcdefghijklmnopqrstuvwxyz012345.lambda-url.us-east-1.on.aws/from-furl
  {"short_url": "https://abcdefghijklmnopqrstuvwxyz012345.lambda-url.us-east-1.on.aws/from-furl", "slug": "from-furl", "url": "https://example.com/", "clicks": 0, "created_at": 1794320804, "expires_at": null}
```

The host names, account ID (`123456789012`) and IDs in the sample events are made up.

## Deploying with AWS SAM

> The template passes `cfn-lint`, and the tests check that it agrees with the code (handler path, table key, TTL attribute, routes, IAM actions). It has not been deployed by the author, and `sam validate` / `sam build` have not been run against it. Please open an issue if a step below does not work.

```bash
sam build && sam deploy --guided
```

Parameters you will be asked for:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `CreateToken` | empty | Shared secret for `POST /links`. Empty means anyone can create links. |
| `DefaultTtlSeconds` | `0` | Lifetime of links created without `ttl_seconds`. `0` = never expire. |

The stack output `ApiUrl` is the base URL. Teardown is `sam delete`, which also deletes the table and every link in it.

What the template creates:

- one Lambda function (Python 3.12, arm64, 128 MB, 10 s timeout);
- one API Gateway HTTP API with three routes (`POST /links`, `GET /links/{slug}`, `GET /{slug}`) and no authorizer;
- one DynamoDB table (on-demand billing, partition key `slug`, TTL on `expires_at`).

The handler reads the method and path from the event itself, so the same code also works behind a Lambda function URL; the template uses an HTTP API. Short URLs in responses use the request's host name unless you set a `BASE_URL` environment variable on the function (for a custom domain, which the template does not set up).

### IAM permissions of the function

Exactly these actions, on the links table only:

| Action | Used for |
| --- | --- |
| `dynamodb:PutItem` | creating a link (conditional, never overwrites a live one) |
| `dynamodb:UpdateItem` | counting a click while resolving a slug |
| `dynamodb:GetItem` | `GET /links/{slug}` |

SAM also attaches the AWS managed policy `AWSLambdaBasicExecutionRole` so the function can write logs. The function cannot scan, query or delete.

### How expiry works

A link with `ttl_seconds` gets an `expires_at` attribute, which is also the table's TTL attribute. DynamoDB removes expired items in the background some time after they expire, not at that moment, so the handler does not rely on it: every lookup also checks `expires_at` against the clock inside the same conditional request, and an expired link is a `404` from the second it expires.

## Security (read this before deploying)

What is built in:

- Target URLs must be `http` or `https`; `javascript:`, `data:`, `file:` and everything else is rejected, as are embedded credentials, control characters and links back to the shortener itself.
- Slugs cannot be overwritten.
- Optional `CreateToken`: when set, `POST /links` requires `Authorization: Bearer <token>` (compared in constant time).
- Request bodies over 4096 bytes are rejected.

What is **not** built in:

- **Authentication beyond one shared token.** The token is a single secret stored as a plain Lambda environment variable, readable by anyone who can view the function's configuration. There are no users, no per-user links and no token rotation. With the default empty token, link creation is open to the world.
- **Rate limiting or quotas.** Nothing stops someone from creating links in a loop or hammering a redirect. The template sets no API throttling of its own and no WAF. Every request costs you Lambda, API Gateway and DynamoDB usage.
- **Target screening.** Any http(s) URL is accepted, including phishing or malware pages. An open shortener on a clean domain is attractive to spammers.
- **Private stats.** Click counts and targets are readable by anyone who has the slug.
- **Deleting or editing links.** There is no endpoint for it; remove items from the table by hand.

## Feature checklist

- [x] Create and resolve short links (custom or random slugs, conditional write)
- [x] Click counts per link
- [x] Link expiry
- [x] Least-privilege IAM in the template (three DynamoDB actions on one table)
- [x] Unit tests that run without AWS
- [x] Local development server (`url-shortener-local`)
- [ ] One-command deploy and teardown (template written and linted, not yet verified by a real deployment)
- [ ] Rate limiting / API throttling
- [ ] Delete and update endpoints
- [ ] Custom domain setup

## Limitations

- Everything in [Security](#security-read-this-before-deploying).
- Click counts are raw request counts. Bots, link previews and repeat visits all count.
- A random slug has 7 characters from a 62-character alphabet. Collisions are retried up to five times; there is no guarantee beyond that.
- Slugs are case-sensitive: `Demo` and `demo` are different links.
- No listing endpoint. To see all links you have to look at the table.
- The local server is for trying things out. It is single-process, in-memory and has no TLS.

## Development

```bash
pip install -e ".[dev]"
pytest
```

`tests/conftest.py` sets dummy AWS credentials before boto3 is imported and every DynamoDB call goes to moto, so the tests cannot reach a real account. One test starts the local server on a random loopback port.

```text
src/url_shortener/handler.py     routing, request parsing, responses
src/url_shortener/store.py       the three DynamoDB calls
src/url_shortener/validation.py  URL, slug and TTL rules
src/url_shortener/local.py       local development server and event builder
template.yaml                    SAM template
examples/events/                 sample HTTP API and function URL events
```

## Contributing

Issues and pull requests are welcome. A report from a real `sam deploy` (what worked, what did not) is especially useful, as the template has only been linted so far. For code changes, add a test and keep the IAM policy in step with the calls in `store.py`; `tests/test_template.py` checks that.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
