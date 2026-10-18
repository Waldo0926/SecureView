# Fixing the 100-user database-pool failure (2026-10-04)

[English](README.md) | [简体中文](README.zh-CN.md)

The staging run for #140 ([report](../REPORT-2026-10-03.md)) found the first limit: at 100
concurrent users, 65–78 % of uploads failed with HTTP 500, `QueuePool limit of size 5 overflow 10
reached`, while server CPU averaged 3 %. This page records how the cause was found, one fix that
made things worse, and the fix that worked, with the same load tool before and after.

## Result

Same machine, same tool, same accounts, `steps --users 20,50,100 --duration 30 --size 1MiB`,
against a local API and MySQL 8.4 (a laptop, not the staging server):

| Concurrent users | Before: uploads failed | Before: ops/s | Before: upload p95 | After: uploads failed | After: ops/s | After: upload p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20 | 0 % | 53.6 | 224 ms | 0 % | 58.4 | 198 ms |
| 50 | 0 % | 54.5 | 470 ms | 0 % | 56.1 | 515 ms |
| **100** | **80 %** (HTTP 500) | **0.33** | **60.5 s** | **0 %** | **56.1** | **969 ms** |

Before, throughput collapsed to almost nothing at 100 users and the failures were the same pool
timeout seen on staging, so the local run reproduces the staging failure. The local link is fast,
which also shows the failure had nothing to do with the network. After, throughput holds at about
56 operations per second at every step and latency grows with the queue, which is the machine's
own limit. Raw summaries and charts: [`before/`](before/REPORT.md), [`after/`](after/REPORT.md).

## How the cause was found

1. **The first guess was wrong, and a measurement showed it.** The report suggested that a file
   transfer might hold its database connection for the whole transfer. Three deliberately slow
   downloads of a 30 MB file were run while watching MySQL: there were **no open transactions**
   during the transfers. The download commits before streaming, which returns its connection.
2. **The failure was reproduced locally** at 100 users (table above), so it could be studied
   without the staging server. The log showed every timeout inside authentication.
3. **The cause:** the upload endpoint is `async`. Authentication left its connection checked out,
   and the upload then ran its database calls on the event loop and awaited the thread pool once
   per chunk to write the staged file, all while holding that connection. With 100 users, 15
   uploads held all 15 connections while waiting for a thread, and all 40 threads were requests
   waiting for a connection. Nothing could move until the 30-second pool timeout.

## The fix that made it worse

Releasing the connection after authentication and before staging, and nothing else, made
**50 users** slow as well (download p95 30 s). The upload's remaining database calls still ran on
the event loop, so now they *waited for a connection on the event loop*, freezing every request
for up to 30 seconds. It was not shipped.

## The fix

- `FileService.upload` is split into a threaded check (key lookups, limits; then the connection
  is released), the async staging (no connection held), and a threaded record (rows, audit,
  publish, commit, with the same rollback and compensation as before). No database call runs on
  the event loop, and no connection is held while waiting for the thread pool.
- Authentication (`get_current_actor`) ends its read-only transaction, so no request carries a
  connection from authentication into the endpoint.
- Tests: a unit test checks the connection is released before staging; the fault-injection test
  now kills the connection at the commit that writes the file row; backend 633 passed on MySQL,
  85.28 % coverage.

## Staging re-run (2026-10-04 evening)

Same tool and parameters as the 2026-10-03 run (`steps --users 5,50,100,5 --duration 60 --size
1MiB`), against staging through an SSH tunnel, with auto-deploy, CI runners, the account limits'
effect and the backups out of the way. Raw data, server metrics and report:
[`staging-rerun/`](staging-rerun/REPORT.md).

| 100 concurrent users | Before (10-03) | After (10-04) |
| --- | ---: | ---: |
| Uploads succeeded | 23 / 103 (**78 % failed, HTTP 500**) | **102 / 102, 0 failed** |
| Downloads decrypted and SHA-256-matched | 23 | 102, 0 integrity failures |
| Upload throughput | 0.19 /s | 0.86 /s |

The fix holds on the real server, not only on a laptop. Two caveats, stated plainly: the generator's
home link still bounds every latency figure (a 100-user upload took ~61 s at p50), and the first
5-user step had 4 dropped connections (`RemoteProtocolError`), as the 50-user step had last time,
which the server log does not show; they are most likely the link or the tunnel and were not
investigated further. The server log had no errors during the run.

## Still to do

- The avatar endpoints are `async` with database calls too. They are rarely used and were not
  changed here.
