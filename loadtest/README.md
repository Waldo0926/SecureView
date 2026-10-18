# SecureView load test

English | [简体中文](README.zh-CN.md)

A client that behaves like the browser: it encrypts every upload with the real file envelope
and decrypts and SHA-256-verifies every download, while timing each operation.

- Plan, known limits, findings and the full procedure:
  [`docs/PERFORMANCE_TESTING.md`](../docs/PERFORMANCE_TESTING.md)
  ([简体中文](../docs/PERFORMANCE_TESTING.zh-CN.md)).
- Local dry run against a disposable stack: `bash loadtest/run_local.sh` (needs `DB_*` for a
  `_test` database).
- Tests: `.venv/bin/python -m pytest tests`.
- Staging run through the public URL: `LOAD_ACCOUNTS=loadtest-accounts.json bash loadtest/run_staging.sh`
  (add `LOAD_LARGE_FILES=1` for the 1 to 500 MiB matrix).
- Results: [`docs/performance/REPORT-2026-10-09.md`](../docs/performance/REPORT-2026-10-09.md) (after the
  fixes, public URL, 2026-10-09), the before-fix baseline
  [`docs/performance/REPORT-2026-10-03.md`](../docs/performance/REPORT-2026-10-03.md) (staging, 2026-10-03/04)
  and the 100-user fix with its staging re-run in
  [`docs/performance/pool-fix-2026-10-04/`](../docs/performance/pool-fix-2026-10-04/README.md).

| File | What it is |
| --- | --- |
| `secureview_load/envelope.py` | The browser's file envelope (AAD-3, AES-128/192/256-GCM and ChaCha20-Poly1305, RSA-OAEP), pinned to `docs/crypto/test_vectors.json`. AES-256-GCM-SIV and XChaCha20-Poly1305 are not implemented here; the load test uses AES-256-GCM |
| `secureview_load/client.py` | One virtual user over the public API |
| `secureview_load/runner.py` | Scenarios: `smoke`, `steps`, `parallel`, `mixed`, `sizes`, `logins`. `sizes` gives each file type its own owner account and deletes each file once it is verified, so the account quotas can stay on |
| `secureview_load/report.py` | Markdown report and charts, lined up with the server sampler |
| `run_staging.sh` | Runs every scenario against the public URL (`https://secureview.tech/api/v1` by default) with the limits on; the large-file matrix only with `LOAD_LARGE_FILES=1` |
| `server_sampler.py` | Runs on the server with the system Python: CPU, memory, disk, network, process and connection counts |
| `../backend/scripts/seed_load_users.py` | Creates the test accounts on the server |

Never point it at a shared server without telling the team; it refuses a non-local host unless
`--confirm-remote` is given. `cleanup` deletes every test account and its files; it waits and
retries when nginx answers 429, so no account is left behind.

Expect the security agent's alert mail at 06:00 the next morning: a run from one address is a burst
of uploads, downloads and sign-ins by the rules' definition, and the check is meant to fail on it.
Confirm the addresses and times against your report, then let the 24-hour window move past it. See
[SECURITY_AGENT.md](../docs/SECURITY_AGENT.md#proactive-alerts-daily).
