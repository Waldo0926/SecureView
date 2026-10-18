# Third-party security scans, 2026-10-04

[简体中文](README.zh-CN.md)

"Secure" should not rest only on our own word. On 2026-10-04 three outside tools were run against
the project: OWASP ZAP against the live staging site, `pip-audit` against the Python
dependencies and `npm audit` against the frontend dependencies. This folder keeps their raw output.

## Summary

| Tool | Target | Result | Action |
| --- | --- | --- | --- |
| OWASP ZAP baseline (`zaproxy:stable`, 1-minute spider, passive rules only) | `https://secureview.tech` | **0 FAIL, 8 WARN, 59 PASS**; no High-risk alerts | Missing headers fixed in nginx; the rest explained below |
| `pip-audit` | `backend/requirements.txt` (what runs in production) | No known vulnerabilities | — |
| `pip-audit` | `backend/requirements-dev.txt` (tests and tooling) | 6 advisories in `httpx2` / `httpcore2` 2.7.0 | Upgraded to 2.12.0; now clean; 570 backend unit and API tests pass |
| `npm audit` | `frontend/` (245 packages) | 0 vulnerabilities | — |

The baseline scan is passive: it spiders the public pages and inspects the responses. It sends no
attack payloads and does not sign in, so it says nothing about the API's authorisation logic;
that is covered by our own tests and the threat model.

## ZAP findings and what was done

| Alert | Risk | Decision |
| --- | --- | --- |
| Strict-Transport-Security not set (on `/assets/*.js`, `*.css`) | Low | **Fixed.** nginx drops every server-level `add_header` in a location that adds its own; `/assets/` adds `Cache-Control`, so the bundle was served without HSTS or nosniff. The headers are now repeated there, and a unit test fails if any location that adds a header drops one. |
| X-Content-Type-Options missing (same files) | Low | **Fixed**, same cause. |
| Permissions-Policy not set | Low | **Fixed.** Camera, microphone, location, payment and USB are switched off; the app uses none of them. |
| Cross-Origin-Opener-Policy / Cross-Origin-Resource-Policy missing | Low | **Fixed**, both `same-origin`. The app opens no cross-site windows and loads nothing from other sites. |
| Cross-Origin-Embedder-Policy missing | Low | **Accepted.** `require-corp` would also block the CDN that the `/docs` API page loads, and it gives nothing extra without cross-origin isolation features we do not use. |
| CSP: `style-src 'unsafe-inline'` | Medium | **Accepted and documented** in the nginx file: Vue writes inline styles for transitions. `script-src` does not have it, so injected markup still cannot run script. |
| Re-examine Cache-control / Storable and cacheable content | Info | Expected: every flagged URL is a public page, `robots.txt`, `sitemap.xml` or the hashed, immutable bundle, all meant to be cached. Sign-in, error and file-download responses send `no-store` themselves. |
| Modern web application | Info | Informational only: ZAP notes that the site is a single-page application. |

## After the fix (re-scan 2026-10-04)

The updated nginx file was installed on the VPS and the scan repeated
([`after-nginx/`](after-nginx/zap-baseline.md)): **0 FAIL, 5 WARN, 62 PASS** (before: 8 WARN, 59 PASS).
The Strict-Transport-Security, X-Content-Type-Options, Permissions-Policy, Cross-Origin-Opener-Policy
and Cross-Origin-Resource-Policy alerts are gone; the headers were also checked directly with `curl -I`
on the bundle. The five left are the accepted ones above (COEP, `style-src 'unsafe-inline'`) and
informational notes.

## Applying the nginx change (done)

The tracked file is `deployment/server/nginx-secureview.conf`, and the live copy on the VPS is
`/etc/nginx/sites-available/fyp-secure-file-platform`. The automatic deploy does not install
nginx configuration; someone with root on the VPS copies the file, runs `nginx -t` and reloads
nginx. The new file passed `nginx -t` on the VPS (nginx 1.24.0) before the extra COOP/CORP lines
were added; those are plain `add_header` lines. After reloading, re-run the scan:

```bash
docker run --rm -v "$PWD":/zap/wrk:rw ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t https://secureview.tech -m 1 -J zap-baseline.json -r zap-baseline.html -w zap-baseline.md -I
```

## Files

- `zap-baseline.html`, `.md`, `.json`: the ZAP report before the fix
- `pip-audit-runtime.json`: runtime dependencies, clean
- `pip-audit-dev-before.txt`, `pip-audit-dev-after.txt`: dev dependencies before and after the upgrade
- `npm-audit.json`: frontend dependencies, clean
