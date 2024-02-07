# lambda-url-shortener

A minimal serverless URL shortener on AWS Lambda and DynamoDB, as a small reference project.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A deployable serverless application.

**The problem it solves:** Good small serverless examples that include tests, local runs and least-privilege permissions are hard to find.

## Who it is for

Developers learning serverless on AWS who want a complete small project to read.

## How it will work

1. You deploy the stack with one command.
2. You create short links through the API.
3. Visiting a short link redirects and counts the click.

## Planned features

Unticked items are not built yet.

- [ ] Create and resolve short links
- [ ] Click counts per link
- [ ] Link expiry
- [ ] Least-privilege IAM in the template
- [ ] Unit tests that run without AWS
- [ ] One-command deploy and teardown

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
sam build && sam deploy --guided
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
