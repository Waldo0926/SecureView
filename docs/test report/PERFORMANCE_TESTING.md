# Performance and capacity testing

[English](PERFORMANCE_TESTING.md) | [简体中文](PERFORMANCE_TESTING.zh-CN.md)

At the 2026-10-01 meeting the supervisor asked for numbers, not "it supports many users": how many
users, files and how large a file the server handles, and where it breaks (items 4, 5 and 6 of the
meeting action list). This page is the plan, the tool, the limits already known before a single
test ran, and what the local dry run found.

**Status (2026-10-04):** the full matrix ran against staging on the night of 2026-10-03/04. The
report, charts, raw summaries, server sampler CSV and run logs are in
[`performance/`](../performance/REPORT-2026-10-03.md); the conclusions are filled in at the end of this
page. Read the report's "Test conditions" before quoting a number: the generator's home link, not
the server, bounds every transfer figure. Tracked in
[#140](https://github.com/jsonrar/fyp-secure-file-platform/issues/140). After the fixes the matrix
was re-run on 2026-10-09 through the public URL
([report](../performance/REPORT-2026-10-09.md)); see the conclusions below.

## What is being measured, and what the server actually does

SecureView encrypts in the browser. The server never encrypts or decrypts a file; for an upload it
validates the envelope, streams the ciphertext to disk while hashing it, and writes the metadata,
grant, wrappings and a hash-chained audit entry in one transaction. A download re-checks the stored
SHA-256 while streaming and appends an audit entry. So "encryption time" in this report is the
**client's** time (measured by the load tool, which does the same work as the browser), and the
server's cost is I/O, hashing, database transactions and the audit chain.

The load tool (`loadtest/`) behaves exactly like the browser: every upload is encrypted with the
same AAD-bound envelope (pinned against `docs/crypto/test_vectors.json`, the browser library's own
known-answer vectors), and **every download is decrypted and compared with the original by
SHA-256**. A run therefore proves integrity on every operation, not just speed.

## Limits known before testing

These come from the code and the server, and they bound what any test can show:

| Limit | Value | Effect on a test |
| --- | --- | --- |
| Server | 8 vCPU, 16 GB RAM, 387 GB disk (237 GB free) | Hardware ceiling |
| API process | One uvicorn process, no `--workers` | All Python work shares one interpreter; sync endpoints run in its thread pool |
| Database pool | SQLAlchemy defaults: 5 connections + 10 overflow | At most 15 DB transactions at once from the API |
| nginx, per source IP | API 10 requests/s (burst 20); sign-in 12/min (burst 8) | One load generator through `https://secureview.tech` measures this limit, not the server |
| Password hashing | `AUTH_PASSWORD_HASH_CONCURRENCY=2`: two Argon2id (64 MiB) verifications at a time; the third gets **429 immediately**, it does not queue | Simultaneous sign-ins beyond 2 fail and must be retried by the client |
| Upload size | 500 MiB plaintext (`MAX_UPLOAD_SIZE_BYTES`), nginx body 501 MB, 300 s proxy timeout | Largest file; a slow link can time out near the top |
| Access token | 30 minutes | The tool renews tokens for long runs |

The nginx row is the setting at the time of these tests. PR #210 (2026-10-09) raised it to 30 API requests/s (burst 60), 60 credential checks/min (burst 30) and 50 uploads in flight per IP.

## Findings from the local dry run

The first local runs already found two concurrency bugs. Both are MySQL deadlocks (error 1213) that
surface to the user as **HTTP 500**, and both are in backend code, so they are recorded here and in
[#139](https://github.com/jsonrar/fyp-secure-file-platform/issues/139) rather than changed inside the
load-test work:

1. **Two simultaneous sign-ins can deadlock.** `_enforce_session_limit` runs
   `SELECT … FROM user_sessions WHERE user_id=? AND status='ACTIVE' FOR UPDATE`. Under MySQL's default
   REPEATABLE READ, for a user with no active session this locks the *gap* in
   `idx_user_sessions_user_status`; two such users (for example the two newest accounts) lock the
   same gap, and each one's `INSERT INTO user_sessions` then waits for the other. One is rolled back.
   Reproduced on the second sign-in of a two-user run.
2. **Download and share can deadlock on the audit chain head.** InnoDB's deadlock report: a share
   transaction held `audit_chain_heads` (id 1) and, inserting its audit row, waited for a shared lock
   on a `users` row (the foreign-key check); a download transaction held an exclusive lock on that
   `users` row and waited for `audit_chain_heads`. Under a 6-user mixed load this failed 4 of about
   1,330 operations (0.3%).

Both are the kind of failure that only appears under concurrency, which is the point of testing.
MySQL's guidance for 1213 is that the application retries the transaction; a narrower fix (a lock
order that never takes the chain head before a user row, or READ COMMITTED for these transactions)
is for the backend owner to choose. The staging run will measure how often they happen at real
concurrency.

## Where the load comes from

The nginx per-IP limits mean the choice of target matters:

| Target | How | Measures | Caveat |
| --- | --- | --- | --- |
| **Origin through an SSH tunnel** (recommended for capacity) | `ssh -N -L 18000:127.0.0.1:8000 <server>`, then `--base-url http://127.0.0.1:18000/api/v1` | The application and database, without nginx or TLS | Large-file throughput is capped by the generator's own upload bandwidth; say so in the report |
| Edge (public URL) | `--base-url https://secureview.tech/api/v1` | The real path including nginx and TLS | From one machine, mostly the 10 req/s limit; useful to *show* the limiter, not capacity |
| Generator on another server (for example the j1900) | Same tunnel from that box | Like origin, with that box's bandwidth | Needs the loadtest venv there |

Since PR #210 the edge limit is 30 req/s (burst 60), so a single generator through the public URL can push harder than in the table above.
The 2026-10-09 after-fix run used the public URL with `loadtest/run_staging.sh`, which keeps the
limits on and needs no tunnel or sshd change.

Running the generator **on** the VPS itself would avoid the network but take CPU from the server
being measured, so it is not recommended.

**The tunnel needs an sshd exception.** Port forwarding is turned off on the server by
default, so the tunnel above opens a local port but every request is reset. For the 2026-10-03
run a temporary forwarding exception limited to `127.0.0.1:8000` was added to the sshd config and
removed again after the run. The exact server config is kept out of this copy.

Add `-o ServerAliveInterval=15` to the tunnel for long runs.

## Test matrix

Mapped to the matrix in the meeting notes. Durations are suggestions; stop raising load when the
error rate passes about 5% or p95 more than triples.

| Dimension | Command (after the common options) | Records |
| --- | --- | --- |
| Concurrent users | `steps --users 1,5,10,20,50,100 --duration 60 --size 1MiB` | p50/p95/p99, ops/s, errors per step |
| File size and type | `sizes --sizes 1MiB,10MiB,50MiB,100MiB,200MiB,500MiB --types pdf,png,jpg,mp4,zip,exe` | Per file: upload, download, share, recipient download, client crypto time, SHA-256 verified |
| Parallel tasks per user | `parallel --users 5 --tasks 1,2,5,10 --duration 60` | Whether one user can starve others |
| Mixed load | `mixed --users <stable> --duration 300` (70% upload, 20% download, 10% share/list) | Closest to real use |
| Sustained load | `mixed --users <near limit> --duration 1800 --window 60` (15/30/60 min) | Drift in p95, memory, connections over time |
| Overload and recovery | `steps --users <stable>,<stable×1.5>,<stable×2>,<stable> --duration 60` | Error types under overload and whether the last step recovers |
| Simultaneous sign-ins | `logins --users 1,2,4,8,16 --rounds 3` | The Argon2id cap and the sign-in deadlock rate, with no retry |

Run `server_sampler.py` on the server for the whole session; the report lines up its CPU, iowait,
memory, disk, network, API and MySQL process CPU/RSS and DB connection counts with each step.

## Running it

**Prerequisites:** the server is otherwise idle; the run is announced to the team; it ends before
the 04:15 backup (or the backup will copy the test files) and before the 05:30 integrity sweep.

**Upload limits:** since 2026-10-04 each account may store 2 GiB and upload 5 GiB per 24 hours, and
nginx allows fifty uploads in flight per address. The `sizes` scenario alone uploads about 5 GiB from
one account, and a soak far more, so for a capacity run set `USER_STORAGE_QUOTA_BYTES=0` and
`USER_DAILY_UPLOAD_BYTES=0` in `/etc/fyp-secure-file-platform/backend.env`, restart
`fyp-backend`, and restore both values afterwards. The SSH tunnel bypasses nginx, so its connection
limit does not apply. Leave `UPLOAD_MIN_FREE_DISK_BYTES` in place: it is what keeps a run from
filling a disk the server shares with other services. Since 2026-10-09 the `sizes` scenario gives
each file type its own owner account and deletes each file once it is verified, so it fits inside the
quotas and that run left them on.

1. On the server, create the test accounts (written 0600; test accounts only):

   ```bash
   cd /opt/mcs21/current/backend && set -a && . /etc/fyp-secure-file-platform/backend.env && set +a
   sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA \
     env PYTHONPATH=$PWD .venv/bin/python scripts/seed_load_users.py \
     --count 100 --out /tmp/loadtest-accounts.json
   ```

   `sudo` resets the environment, so without `--preserve-env` the script falls back to other
   database settings and fails with `Access denied for user 'fyp_user'`.

   Copy the file to the generator (`scp <server>:/tmp/loadtest-accounts.json .`) and delete it from
   the server.
2. Start the sampler on the server:
   `python3 /opt/mcs21/current/loadtest/server_sampler.py --interval 2 --out /root/loadtest-metrics.csv`
3. On the generator, open the tunnel and run the scenarios:

   ```bash
   cd loadtest && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
   ssh -N -L 18000:127.0.0.1:8000 <server> &
   .venv/bin/python -m secureview_load --base-url http://127.0.0.1:18000/api/v1 \
     --accounts loadtest-accounts.json --confirm-remote --out results steps --users 1,5,10,20,50,100
   ```

   The tool refuses any host other than this machine without `--confirm-remote`.

   To run through the public URL instead, `LOAD_ACCOUNTS=loadtest-accounts.json bash loadtest/run_staging.sh`
   runs every scenario in order against `https://secureview.tech/api/v1` by default. The large-file
   matrix (about 5 GiB each way) only runs with `LOAD_LARGE_FILES=1`.
4. Stop the sampler (Ctrl-C), copy the CSV back, and build the report:
   `.venv/bin/python -m secureview_load.report results --server-metrics loadtest-metrics.csv --out results/REPORT.md`
5. Delete the accounts and all their files through the API:
   `.venv/bin/python -m secureview_load --base-url … --accounts loadtest-accounts.json --confirm-remote cleanup`

**Storage:** at 1 MiB per upload a 100-user step can write several GiB. The cleanup removes them;
check `df -h` before and after.

## Dry run on a local stack

`loadtest/run_local.sh` runs every scenario at a small size against a disposable local API and
MySQL (database name must contain `_test`), writes the report, and deletes the accounts. Its numbers
describe a laptop, not the server; it exists so the real run has no surprises.

```bash
DB_HOST=127.0.0.1 DB_PORT=3310 DB_USER=root DB_PASSWORD=... DB_NAME=fyp_loadtest_test bash loadtest/run_local.sh
```

The tool's own tests: `cd loadtest && .venv/bin/python -m pytest tests`.

## Conclusions

### 2026-10-09 re-run (after fixes, public URL)

Release `ac5e2b0`, run from a home broadband laptop through `https://secureview.tech` (HTTPS and
nginx, limits on). Full numbers and test conditions are in
[the 2026-10-09 report](../performance/REPORT-2026-10-09.md).

- **Integrity and errors:** 18,256 operations; 7,444 downloads decrypted and SHA-256-verified with 0
  integrity failures; 0 server 5xx (the backend log has 25,637 requests and no 500).
- **Capacity:** every request up to 50 concurrent users succeeded (upload p95 134 ms at 1 user, 3.3 s
  at 50; download p95 76 ms at 1 user, 9.5 s at 50). At 100 users there was no server error. The 644
  uploads refused across the two 100-user steps were 429s from nginx's limit of 50 uploads in flight
  per address, because all the load came from one address. Before the fix the same step gave 65 to
  78 % HTTP 500.
- **Large files:** pdf, png, jpg, mp4, zip and exe at 1 to 500 MiB: 36/36 files uploaded, shared and
  downloaded by the recipient, 72/72 downloads byte-exact. 500 MiB took about 48 s up and 43 s down
  on this link.
- **Bottleneck:** throughput levels off at about 8 to 9 MiB/s each way (about 70 Mbit/s) from 10
  users, while server CPU averages 4.5 % (peak 42 %) and API memory stays at 199 MiB. The network
  is the limit, not the application.
- **Limits and retries:** 713 × 429 in total (644 uploads in flight, 1 API rate, 68 sign-in cap and
  credential limit), all limits working as designed, and 1 × 413 from the 2 GiB account quota (the
  same file then went through from an empty account). MySQL reported 8 deadlocks; each was retried
  once by #139 and succeeded, which the #202 log line made visible.
- **Not re-run:** the 15, 30 and 60 minute soaks.
- **The next morning:** the security agent's daily check (06:00 on 2026-10-10) failed with 43 High
  findings, every one of them this run: the upload and download bursts of the five busiest accounts,
  the 68 failed sign-ins of the cleanup at already-deleted accounts, and the 32 accounts that signed in
  right after them. That is the agent doing its job on real traffic; see
  [SECURITY_AGENT.md](../SECURITY_AGENT.md#proactive-alerts-daily) for how it was confirmed and what the
  rules now say about it.

### Before-fix baseline (staging run, 2026-10-03/04)

From the meeting notes, filled from [the staging report](../performance/REPORT-2026-10-03.md):

- **Capacity:** On this server (8 vCPU, 16 GB), the system served 5 concurrent users on a mixed
  upload/download/share load for 108 minutes in total (19,372 operations) with no server-side
  error; at 1 MiB files upload p95 was 2.1–4.9 s and download p95 1.7–2.3 s over the test link.
  Up to 50 concurrent users the server returned no error (the failures seen at 10–50 users are
  the SSH tunnel on the generator side, see the report). At 100 concurrent users 65–78% of
  uploads failed with HTTP 500. Parallel tasks per user (1/2/5/10) caused no server error.
- **Bottleneck:** Beyond 50 users the limit is the single API process's database pool (5 + 10
  connections, 30 s wait): at 100 users requests time out waiting for a connection while server
  CPU averages 3% and memory is flat. **Fixed 2026-10-04 (PR #163):** uploads held a connection
  while awaiting the thread pool, whose threads were waiting for connections; the upload's database
  work now runs in the pool and holds no connection while staging. Locally the 100-user step went
  from 80% failed uploads to none at 56 ops/s ([details](../performance/pool-fix-2026-10-04/README.md));
  re-run on staging the same night: 102 of 102 uploads succeeded at 100 users, 0 integrity failures ([results](../performance/pool-fix-2026-10-04/README.md#staging-re-run-2026-10-04-evening)). Beyond that, scaling means more uvicorn workers and a larger
  pool, re-measured with this tool. Below that, every transfer number was bounded by the network: the VPS port is ~100 Mbit/s,
  and the test link was ~24 Mbit/s up and ~13 Mbit/s down.
- **Large files:** Every type (pdf, png, jpg, mp4, zip, exe) up to 500 MiB round-trips byte-exact
  (144/144 operations, every download SHA-256 verified); 500 MiB took p50 146 s up and 295 s down
  over a ~24 Mbit/s up / ~13 Mbit/s down link. Across the whole run, 5,094 downloads were verified
  with 0 integrity failures.
- **Sign-in:** The server verifies two passwords at a time by design; 4, 8 and 16 simultaneous
  sign-ins saw 50%, 75% and 71% rejected immediately with HTTP 429 for retry, and none failed with
  a 500 or a deadlock.
- **Recovery and monitoring:** After the 100-user overload the next 5-user step had 0 errors with
  no restart or manual action, and each deliberate overload produced exactly one alert email from
  `mcs21-observe` that cleared on the next check.
