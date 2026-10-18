# OWASP ZAP baseline re-scan, 2026-10-12

[简体中文](README.zh-CN.md)

The [2026-10-04 scan](../scans-2026-10-04/README.md) was eight days and 45 merged pull requests old
by the final presentation week, so the same passive baseline was run again against the live site at
release `1eb56d8` (#224). This folder keeps the raw output; the decisions on each alert are in the
2026-10-04 README and have not changed.

## Result

| Tool | Target | Result |
| --- | --- | --- |
| OWASP ZAP baseline (`zaproxy:stable`, 1-minute spider, passive rules only) | `https://secureview.tech` at `1eb56d8` | **0 FAIL, 5 WARN, 62 PASS**; no High-risk alerts. Identical to the 2026-10-04 after-fix scan |

The five WARN alerts are the same five as after the nginx fix on 2026-10-04:

| Alert | Risk | Status |
| --- | --- | --- |
| Cross-Origin-Embedder-Policy missing | Low | Accepted: `require-corp` would block the CDN the `/docs` page loads, for nothing the app uses |
| CSP: `style-src 'unsafe-inline'` | Medium | Accepted and documented in the nginx file: Vue writes inline styles for transitions; `script-src` has no `unsafe-inline` |
| Re-examine Cache-control directives | Info | Public pages and the hashed bundle are meant to be cached; sign-in, error and download responses send `no-store` |
| Storable and cacheable content | Info | Same |
| Modern web application | Info | ZAP noting a single-page application |

The headers the first scan found missing on the static bundle (Strict-Transport-Security,
X-Content-Type-Options, Permissions-Policy, Cross-Origin-Opener-Policy, Cross-Origin-Resource-Policy)
are still present: 62 PASS, as on 2026-10-04 after the fix.

As before, the baseline scan is passive. It spiders the public pages and inspects the responses, sends no
attack payloads and does not sign in, so it says nothing about the API's authorisation logic; that is
covered by our own tests and the threat model. `npm audit` runs in the `frontend` CI job on every pull
request and was clean on `1eb56d8`.

## How it was run

From a laptop, the same command as on 2026-10-04:

```bash
docker run --rm -v "$PWD":/zap/wrk:rw ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://secureview.tech -m 1 -J zap-baseline.json -r zap-baseline.html -w zap-baseline.md -I
```

## Files

- `zap-baseline.html`, `.md`, `.json`: the ZAP report of 2026-10-12
