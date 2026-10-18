# Security Policy

SecureView runs in production at https://secureview.tech. This repository is a published copy of its source; the running service is maintained by the team.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Email **wensx0926@gmail.com** with the affected page or endpoint, the steps to reproduce, what you expected and what happened, and what you think the impact is. You should get a reply within a week. Please do not send real credentials or other people's files; describe where something leaks rather than sending the secret.

## What is in scope

- A plaintext file, file key, private key or encryption passphrase leaving the browser.
- Reading, sharing or downloading a file without a valid grant, or after it was revoked.
- A gap in the audit chain, or an action that leaves no audit record.
- Bypassing login, session, rate limits or administrator checks.

## What is out of scope

- Problems that need an attacker who already controls the user's device or browser.
- Findings from automated scanners with no demonstrated impact.
- Denial-of-service or high-volume testing against the production service. Please test against your own deployment.

## Responsible testing

Use accounts and files you own. Do not access other users' data, and do not publish a finding before there has been a reasonable opportunity to fix it.

The security model, its known limitations and the checks the project runs are described in [docs/SECURITY_OVERVIEW.md](docs/SECURITY_OVERVIEW.md) and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).
