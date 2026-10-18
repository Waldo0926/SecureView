# Live tamper demonstration

[简体中文](TAMPER_DEMO.zh-CN.md)

About 40 seconds of the 4-minute demo: change the stored ciphertext on the server while the
audience watches, then show the recipient's download refusing it. It answers "you say it is
encrypted and checked; show me" with something the audience sees happen.

The tool is [`backend/scripts/demo_tamper.py`](../../backend/scripts/demo_tamper.py). It only
touches files owned by an account whose name starts with `demo-`, refuses a file the named owner
does not own, keeps the original bytes and row values until `restore`, and refuses a second
tamper before a restore.

## What it shows

| Command | What it does to the server | What the audience sees | Which check stops it |
| --- | --- | --- | --- |
| `flip` | Changes one byte in the middle of the stored ciphertext | Download refused, "The encrypted file could not be verified"; the row turns **Modified** | The server hashes the object before streaming it and compares it with the recorded SHA-256 |
| `forge` | Changes one byte **and** rewrites the recorded digest and size to match, as an attacker with both storage and database write access would | The same refusal | The digest the hash-chained audit log recorded at upload no longer matches the rewritten column |
| `restore` | Puts the original bytes, digest, size and status back | Download works again | — |
| `list` | Nothing; prints the owner's files with their ids | — | — |

The third layer, the browser's AES-GCM authentication tag, would catch an attacker who also got
past both server checks. Showing it live would mean rewriting the audit chain on staging, so it is
left to `frontend/src/crypto/download.test.ts` and the `tamper-drill` CI job; say so if asked.

## Before the presentation (once)

1. On staging, sign in as two demo accounts (for example `demo-alice` and `demo-bob`; **the user
   creates these**, the assistant does not register accounts on the live site).
2. As `demo-alice`, upload a small, readable file (for example `quarterly-results.txt`) and share
   it with `demo-bob`. Download it once as `demo-bob` to check it opens.
3. Find the file's id on the server (commands below, with `list` in place of `flip` and no
   `--file-id`). It prints each of the owner's files with its id and marks any left tampered.
4. Rehearse the whole sequence below once, ending with `restore`.

## During the demo

Have two windows ready: the browser signed in as `demo-bob` on My Files → Shared with me, and a
terminal already connected to the server.

Set up the terminal beforehand, then leave it:

```bash
ssh <server>
```

```bash
cd /opt/mcs21/current/backend && set -a && . /etc/fyp-secure-file-platform/backend.env && set +a
```

Then, in front of the audience:

```bash
sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA,ENCRYPTED_FILE_DIR PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py flip --owner demo-alice --file-id <id>
```

Say: "I am the server's administrator, or someone who broke into it. I have just changed one byte
of Alice's file on disk." Switch to the browser and press Download as `demo-bob`. The download is
refused and the row shows **Modified**.

Optional, if there is time: `restore`, then `forge` the same way and download again. Say: "Now I
also edit the database so the stored digest matches. It is still refused, because the digest was
also written into the tamper-evident audit chain at upload."

Always finish with:

```bash
sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA,ENCRYPTED_FILE_DIR PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py restore --owner demo-alice --file-id <id>
```

Then, as `demo-alice`, click the file's **Modified** status badge in My Files once. That re-runs
the integrity check, and the badge goes back to **Verified**.

## Restoring from backup instead, live

To show recovery as well, put the file back the way an administrator would after a real
incident, not with `restore`:

1. As the administrator, open Admin → **Integrity** and press **Scan now**. The file is listed as
   **MODIFIED**.
2. Open **How to put the original back** under it. Copy the first command, paste it in the
   server terminal (logged in as root) and press Enter. It changes nothing and ends with
   `"result": "dry_run_would_restore"`, with the nightly backup it would use as `manifest_id`.
3. Copy the second command (the same, ending in `--apply`) and paste it. It prints
   `"result": "restored"` once the original is back and has been re-verified.
4. Press **Scan now** again. Nothing is listed as damaged.

Both commands run as pasted: they read the server's own nightly backup in
`/var/backups/mcs21-daily`, which needs no key. `demo_tamper.py` notices that the file was put
back this way, so `list` no longer marks it and the next `flip` works without a `restore`.

Say: "The damaged copy is kept in quarantine, the original comes from last night's backup, it is
checked against the fingerprint recorded at upload, and the restore is written to the audit log."

## Things to know

- The backup is kept in `/var/lib/fyp-secure-file-platform/demo-tamper/` (mode 0600, owned by
  `fypapp`) until `restore` removes it. If the terminal drops mid-demo, run `restore` later; it
  still works.
- The nightly integrity sweep and the security agent will report a file left tampered, and may send
  an alert email. Restore straight after the demo. If an alert does arrive during the talk, it is
  evidence that the monitoring works. `list` shows whether anything is still tampered.
- The refusal message is the same for both commands on purpose: the server tells a client that the
  stored copy failed its check, not which check failed.

## Checked

Locally, against MySQL 8.4 with the real frontend (2026-10-04): `flip` → download refused with
"The encrypted file could not be verified" and the row shown as Modified; `restore` → the
download decrypted to the original text; `forge` → refused by the audit-chain anchor; `restore`
→ download worked again; clicking the badge turned the row back to Verified; `list` printed the
file and its id. Refusals checked: an owner without the `demo-` prefix, an owner who does not own
the file, a second `flip` before `restore`, and `flip` without `--file-id`.
