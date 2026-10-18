# Reflection: what is still missing, and how to fix it (kept up to date)

[English](REFLECTION.md) | [简体中文](REFLECTION.zh-CN.md)

The shortcomings we found ourselves: the problem, the fix, its priority and where it stands. When an
item is done, change its status to Done with the PR number. Anything not finished stays as it is; never
mark it done early. What to say and where the evidence is: [TALKING_POINTS.md](TALKING_POINTS.md).

Last updated: 2026-10-09

## How these were found

- **A first-time-user walkthrough (2026-10-04):** registering a brand-new account on a local stack and
  going through register → save private key → sign in → upload → unlock → share, noting every point
  where a newcomer would hesitate or get stuck.
- **The capacity test (#140):** it measured the first performance bottleneck.
- **The threat model (`docs/THREAT_MODEL.md`):** findings already recorded as open.
- **The Final Presentation guidance (Ed #66):** what the nine parts of a 12-minute talk need that we
  do not have yet.

## 1. Usability

| # | Problem | Fix | Priority | Status |
| --- | --- | --- | --- | --- |
| — | The upload's seal receipt could not be put away, though AC7 asks for a dismissible progress pipeline. | A close button once nothing is running. | Must | **Done** ([PR #200](https://github.com/jsonrar/fyp-secure-file-platform/pull/200)) |
| — | A user who still knew their passphrase could change it only with the private key file, which should stay locked away. | Change it in Settings with the current passphrase. | Should | **Done** ([PR #201](https://github.com/jsonrar/fyp-secure-file-platform/pull/201)) |
| 2 | Each file row has six unlabelled icons. Share, a core feature, is just an icon; Share, Delete and Access history have no accessible name; at ~800 px the Help assistant button covers the Delete icon. | Show Download (decrypt), Share and Delete with labels; put Download encrypted, Request recovery and Access history under "More"; give every button an accessible name; fix the overlap. | Must | **Done** (PR #159). The homepage picture guide was re-captured with the new row actions (PR #166, and again after the redesign in PR #192). |
| 8 | Sharing has no confirmation: it happens the moment a username is entered, so a typo shares with a stranger. | Before sharing, show "Sharing with X (key fingerprint ab12…)" and ask to confirm. The fingerprint can be checked in person, which also guards against the server substituting the recipient's public key (a man-in-the-middle). | Strongly recommended | **Done** (PR #160): confirmation step, fingerprint computed in the browser, the user's own fingerprint in Settings, a warning when a recipient's key changes. Threat model T-S5 mitigated. |
| 10 | Registration is one form with six required fields and three secrets to understand (login password, encryption passphrase, private-key file), then a second sign-in. | Split into two steps (account, then encryption), explain in one sentence why there are two passwords, and sign the user in straight after. | Optional (the demo uses prepared accounts) | **Done** (PR #161): step 1 account, step 2 the passphrase with a "why a second password" note; registering signs the user in and opens the session key with the key just generated. |
| 11 | A first sign-in has no guidance; a newcomer does not know the flow is upload → share → recipient downloads and verifies. | A three-step checklist on the dashboard that ticks itself as each step is done; the live demo follows it too. | Optional | **Done** (PR #162): three steps on the dashboard that tick themselves from the account's own audit trail, each linking to where it is done; hideable per account. |
| — | An administrator could disable an account but not help someone who had lost their login password, and a signed-in user had no way to change it (the API existed, the page did not). | Account details and a login-password reset for administrators (temporary password shown once, sessions revoked, holder emailed); a "Login password" card in Settings. | Strongly recommended | **Done** ([PR #197](https://github.com/jsonrar/fyp-secure-file-platform/pull/197)). The holder is now forced to pick a new password at the next sign-in ([PR #212](https://github.com/jsonrar/fyp-secure-file-platform/pull/212), schema `0011_must_change_password`). Remaining: the user list search covers only the loaded page. |
| — | Uploads finished "instantly" and looked unencrypted. | Show the real encryption steps, measured times and the bytes before and after. | Must | **Done** (PR #156) |
| — | Supervisor feedback: the "Encryption Complete" button at the end of an upload was still pressable and uploaded the files again, and the algorithm list gave no guidance on which one to pick. | The finished state is a green status, not a button, and a file is never uploaded twice; each algorithm in the dropdown has a grade (for example "Max · Recommended") and an explanation box below it. | Must | **Done** ([PR #215](https://github.com/jsonrar/fyp-secure-file-platform/pull/215)) |
| — | After the "Sealed" restyle the pages still disagreed with each other: headings left-aligned on some pages and centred on others, widths from a narrow strip to full width, the sidebar vanishing on Help and Education, 12 px body text. We found it by looking page by page, which is why it took several rounds. | A shared `PageHeader` and one content container, two-column Settings and Profile, the sidebar on every signed-in page, and a committed audit script (`frontend/scripts/layout-audit.mjs`) that measures all pages in five configurations, so this is checked by a script and not by eye. | Strongly recommended | **Done** for headers, widths, sidebar and text size ([#183](https://github.com/jsonrar/fyp-secure-file-platform/issues/183)); dark-mode primary, heading pills and the sign-in layout are #184 (done); Access Records failed requests, step-dot targets and the 768 px overflow are #185 (done in code). Remaining weakness: the audit measures layout, not whether a page is good (the home comparison table and footer were fixed by eye in [PR #194](https://github.com/jsonrar/fyp-secure-file-platform/pull/194); line breaks in headings and intros are now measured by `text-audit.mjs`, [PR #195](https://github.com/jsonrar/fyp-secure-file-platform/pull/195)), and pages still have no component tests. |
| — | The file details panel (SHA-256, who can open it, every action) was hidden behind a small grey "Details" link that read as a caption, and it opened over a dimmed page, so the list could not be seen or switched while it was open. At about 1100 px the table headings overlapped. | Whole row and file name open it, a bordered Details button in Actions, a non-modal side panel that switches when another row is clicked (bottom sheet on a phone); fewer columns between 1024 and 1279 px. | Strongly recommended | **Done** ([PR #193](https://github.com/jsonrar/fyp-secure-file-platform/pull/193)). Remaining: no component test for the table or the panel, only screenshots and the browser suite; the Help videos were re-recorded on 2026-10-10 and show the Details button. |

## 2. Performance and reliability

| # | Problem | Fix | Priority | Status |
| --- | --- | --- | --- | --- |
| — | `mcs21-deploy` never pruned its pre-deploy backups: 178 sets and 76 GB by 2026-10-08, on a disk shared with other services. | Keep the newest 10 after a healthy deployment. | Must | **Done** ([PR #204](https://github.com/jsonrar/fyp-secure-file-platform/pull/204)): installed 2026-10-08; the first run removed 175 sets, 81 GB → 7.5 GB, disk 69 % → 51 % |
| — | New npm advisories (Vue SSR, source-map-js) failed the CI audit gate for every frontend change. | Upgrade rather than add an exception. | Must | **Done** ([PR #203](https://github.com/jsonrar/fyp-secure-file-platform/pull/203)) |
| — | A deploy could hang for minutes on one slow pip connection (2026-10-05, #195), and a failed build left its directory on the server. | Wall-clock limit per `pip install` attempt, three attempts, clean up on failure. | Strongly recommended | **Done** ([PR #196](https://github.com/jsonrar/fyp-secure-file-platform/pull/196)). Remaining: every release still downloads all requirements from scratch (`--no-cache-dir`); a shared wheel cache would make deploys faster but needs care with the immutable release layout. |
| 6 | At 100 concurrent users the API's 15 database connections ran out and 65–78 % of uploads got HTTP 500 while CPU was at 3 %. Measured cause: an upload held its connection while waiting for a thread pool whose threads were themselves waiting for connections. It was not the file transfer, which was the first guess. | Release the connection before handing work to the thread pool, then re-run 100 users on staging with the same tool for a before/after comparison. | Strongly recommended | **Done** (PR #163, staging re-run #172): 100 users locally 80 % failed → 0 %, 0.33 → 56 ops/s; on staging 102 of 102 uploads and 102 of 102 verified downloads succeeded. Re-measured on 2026-10-09 through the public URL (release `ac5e2b0`, HTTPS and nginx): 0 server errors at 100 users, every request OK up to 50, 7,444 verified downloads with 0 integrity failures; the only refusals at 100 users were 429s from the per-address upload limit ([report](../performance/REPORT-2026-10-09.md)). |
| — | Load-test transfer speeds on 2026-10-03 were bounded by the home link (~24 Mbit/s up), so the server's own port (~100 Mbit/s) was never the limit. | State it in the report; use a better-connected generator if one is available. | State it | **Done** (2026-10-09): the re-run came from an 821/493 Mbit/s link, so the VPS's 100 Mbit/s port became the limit (a single 500 MiB transfer at 87 to 98 Mbit/s, server CPU 4.5 % on average). Stated in both reports ([2026-10-09](../performance/REPORT-2026-10-09.md)). |
| — | `db_retry` does not log a retry, so we can show no deadlock reached a user but not whether a retry fired. | Log a warning on each retry. | Optional | **Done** ([PR #202](https://github.com/jsonrar/fyp-secure-file-platform/pull/202)): one warning on `secureview.db` per retry, with the MySQL error code and attempt number only. The 2026-10-09 load test logged 8, each succeeding on the second attempt. |
| — | In-browser encryption peaks at about 4× the file size in memory, so 500 MB files likely fail on phones (threat model F-19). | A large-file warning exists; a real fix is chunked streaming encryption, beyond this semester. | State it | Recorded in the threat model |
| — | A docs-only push could cancel the CI run of the code merged just before it and then skip the tests itself, so that code was never promoted to `deploy` (seen on 2026-10-04: #168 cancelled #169's run). | Judge a push to `main` against `deploy`, not against the previous push. | Must | Done: [#171](https://github.com/jsonrar/fyp-secure-file-platform/pull/171) |
| — | On the self-hosted runners' first runs the `backend` job took about 33 minutes against 3–6 for every other job. Its uv cache had never been saved, because the first run failed before the save step. | Check whether the CPU cap is the cause before raising it, since the cap protects production on the same VPS. | Should | Done, no change needed: with the cache saved, `backend` took 1 min 34 s and the whole run about 8 minutes (#171). It was the cold cache. |

## 3. Security

| # | Problem | Fix | Priority | Status |
| --- | --- | --- | --- | --- |
| — | Weak encryption passphrases (`password123`, `aaaaaaaaaa`) passed the length-only check (threat model F-04). | Refuse common, patterned and account-derived passphrases in the browser; suggest four random words. | Strongly recommended | **Done** ([PR #205](https://github.com/jsonrar/fyp-secure-file-platform/pull/205)); browser-side only |
| — | No per-account storage quota: one account could fill a disk shared with other services (threat model T-D2 / F-09). | Per-account quota, a 24-hour upload volume, a free-disk floor, per-IP concurrent uploads in nginx, an `UPLOAD_BURST` rule. | Must | **Done** (PR #157) |
| — | The server cannot scan for viruses (inherent in zero-knowledge encryption). | Warn before downloading a shared program or macro file; rely on endpoint antivirus; never send hashes to a third party. | Must | **Done** (PR #157) |
| 12 | No third-party security scan; "secure" is only our own word. | An OWASP ZAP baseline scan of staging plus `pip-audit` / `npm audit`; fix what they find and commit the report. | Optional | Done: [scans-2026-10-04](../security/scans-2026-10-04/README.md). ZAP: 0 FAIL, 8 WARN, no High. It found a real gap: the JS/CSS bundle was served without HSTS or nosniff, because an nginx location that adds its own header silently drops the server-level ones; fixed, with a test. Six advisories in a test-only HTTP client fixed by upgrading. The nginx change was installed on the VPS on 2026-10-04. Re-scanned 2026-10-12 at the presentation-week release: 0 FAIL, 5 WARN, 62 PASS, unchanged ([scans-2026-10-12](../security/scans-2026-10-12/README.md)). |
| — | The server sees metadata (file name, size, type, times). | A design trade-off; say so in the talk. Encrypted file names are future work. | State it | Recorded in the threat model |
| — | No multi-factor sign-in. | Future work. | State it | — |
| — | Volumetric DDoS cannot be stopped in the application. | A real deployment sits behind a service such as Cloudflare; present it as a known risk outside scope. | State it | — |

## 4. Presentation and evidence

| # | Problem | Fix | Priority | Status |
| --- | --- | --- | --- | --- |
| 3 | "We encrypt" has no moment the audience can see for themselves. | A tamper demonstration: change one byte of stored ciphertext and the recipient's download fails at once. The CI tamper drill already does this; it needs a demo script. | Must | Done: `backend/scripts/demo_tamper.py` and [TAMPER_DEMO.md](TAMPER_DEMO.md). Rehearsing it showed two things: a refused download only said "Download failed", because the error body arrived as bytes and was never read (fixed, the row now turns Modified); and rewriting the database digest as well is still caught by the audit-chain anchor, a second layer worth showing. |
| 1 | Only about 4 of the 12 minutes are demo, and a live demo can lose the network, hang or be mis-clicked. | A 4-minute demo script; **demo accounts on staging must be created by the user** (the assistant does not register accounts on the live site); a recorded backup video. | Must | Script done: [DEMO_SCRIPT.md](DEMO_SCRIPT.md) (timed steps, lines to say, checklists, fallbacks). The demo accounts exist on staging, the backup video is recorded ([media/demo-backup.mp4](media/demo-backup.mp4)) and the picture guide was re-captured (PR #166); after the redesign all of it, and the three Help videos, was re-shot on 2026-10-05 (#186), the guide in English and Chinese. `quarterly-results.txt` is pre-shared from `demo-alice` to `demo-bob` on staging (verified 2026-10-08). |
| 4 | The slides had no diagrams. | One flow diagram for the slides (upload, browser encryption, share, authorised download, decryption) and one sequence diagram of sharing that follows the code; recovery shown with screenshots. | Must | **Done** (2026-10-09): [`diagrams/secureview-flow.png`](diagrams/secureview-flow.png) (and `.svg`), the sharing sequence diagram in [SECURITY_FLOWS.md](../SECURITY_FLOWS.md), the AC4a screenshots in [`screenshots/`](screenshots/), and the requirement-to-demo map [RTM_DEMO_MAP.md](RTM_DEMO_MAP.md). Deliberately no other diagrams |
| 5 | NFR2 (usability) has no formal result: the study was not run (#115, closed as not planned). | Say it is supported by informal real use, never that a study verified it. | Must | Done: the wording to use, and what not to say, is in TALKING_POINTS §10. |
| 7 | No real-user data. | 5–8 students who have never used it, scored with SUS. | Strongly recommended | Not doing: #115 closed as not planned on 2026-10-04. The supervisor, the team, the Teaching Team and other students have used staging instead; that is informal use, with no SUS score. The study kit was deleted on 2026-10-05. |

## Order (decided 2026-10-04)

**2 → 8 → 10 → 11 → 6 → 3 → 12 → 1 → 4 → 5**

- 2, 8, 10 and 11 first: they are the usability problems. (The usability study, item 7, was later dropped; see its row.)
- 6 needs an evening on staging for the re-run, so it follows the code changes.
- 3 and 12 produce evidence and do not depend on the final UI.
- 1, 4 and 5 last, because the demo script, screenshots and numbers must come from the final version.

## Explicitly out of scope this semester

- Chunked streaming encryption (the large-file-on-phone problem)
- Encrypting file names and other metadata
- Multi-factor sign-in
- Network-level DDoS protection
- Files above 1 GB, collaborative editing, encrypted full-text search (see "Explicitly deferred" in `TODO.md`)
