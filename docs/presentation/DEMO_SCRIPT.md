# Four-minute live demo script

[简体中文](DEMO_SCRIPT.zh-CN.md)

The demo slot is 3:30–7:30 of the 12-minute presentation ([TALKING_POINTS.md](TALKING_POINTS.md) §0).
It shows the three claims the audience should leave with: the file is encrypted before it leaves
the browser, only the named person can open it, and a changed file is refused. Everything runs on
staging, `https://secureview.tech`.

## Cast and setup

| Who | Where | Signed in as |
| --- | --- | --- |
| Presenter ("Alice") | Browser window A, left half of the screen | `demo-alice` |
| The colleague ("Bob") | Browser window B, right half, **a separate browser profile** so the two sessions do not share storage | `demo-bob` |
| The administrator | Browser window C, a third profile, opened on Admin → Security agent and minimised until step 5 | the team's ADMIN account on staging |

`demo-alice` and `demo-bob` already exist on staging (seeded 2026-10-04, so no email code is needed;
login password `<demo-password>`, passphrases kept by the project owner). The names must start with `demo-`,
because the tamper tool refuses any other account. Use passphrases that differ from each other and
from any real account.

Before the presentation, as `demo-alice`, upload `quarterly-results.txt` (a short readable text file)
and share it with `demo-bob`, then change one byte of it on the server with `demo_tamper.py flip`
(the exact steps are under "Preparing the tampered file" below). On stage Bob therefore has two
shared files: `board-minutes.pdf`, uploaded live, which opens, and `quarterly-results.txt`, which is
refused. No terminal is used during the talk.

## The script

| Time | Step | Do | Say |
| --- | --- | --- | --- |
| 0:00–0:15 | Set the scene | Window A is already on **Education** with the AES-256-GCM card open (AC6); point at it, then at the two windows | "Everything the app does is explained here, with a playground. Alice wants to send Bob a confidential report. Neither of them trusts the server, and neither should you." |
| 0:15–1:05 | **1. Upload** | In A: Upload → choose `board-minutes.pdf`, leave the algorithm on **AES-256-GCM · Max · Recommended** (the box under it says why) → Start Encryption. Let the four stages play (AC7). The button turns into a green **Encryption Complete** status that cannot be pressed again, so nothing is uploaded twice. Close the receipt with its close button | "Every step you see is timed for real: encrypt in the browser with a fresh key, wrap that key, upload. Look at the bytes: the file starts `%PDF`; what the server receives is noise." |
| 1:05–1:45 | **2. Share** | In A: My Files → `board-minutes.pdf` → Share → type Alice's passphrase in the dialog that opens → type `demo-bob` → Share. The confirmation shows Bob's key fingerprint → **Confirm and share**. In B: Settings shows the same fingerprint | "Before anything is sent, Alice sees which key the file will be locked to. Bob reads his fingerprint from his own Settings: they match, so only Bob can open it. The server never had the key." Then Confirm and share |
| 1:45–2:20 | **3. Open** | In B: My Files → Shared with me → `board-minutes.pdf` → the download icon (its tooltip reads **Download and decrypt**). The passphrase dialog appears every time: type Bob's passphrase. Open the saved file | "Bob unlocks with his own passphrase, never Alice's. The file is checked on the way out, then decrypted on his device." "His key is sealed under his passphrase, so the browser asks for it on every download, and locks it again straight after." |
| 2:20–2:45 | **3b. Audit** | In A: My Files → `board-minutes.pdf` → Details → **Access history** | "Alice can see who opened it and when: her upload, her share, and Bob's download a few seconds ago. Every entry is chained to the one before, so the log itself cannot be quietly edited." |
| 2:45–3:15 | **4. Tamper** | Still in B, Shared with me. Point at `quarterly-results.txt`, the second file Alice shared, which was changed on the server before the talk (preparation below). Press its download icon and type Bob's passphrase | "Last night one byte of this file was changed on the server's disk, the way an administrator or an intruder could. Bob asks for it." The download is refused with "The encrypted file could not be verified", a red line appears under the list, the row reads **Modified**, and nothing is saved. "Changed, so refused. Nobody was asked to trust us." |
| 3:15–3:40 | **5. The agent saw it** | In window C (the administrator): Admin → **Security agent**. The top finding is **Critical**, `INTEGRITY_DAMAGE`, naming `quarterly-results.txt` | "The administrator did not have to notice. The security agent reads the audit log and the integrity checks every day and ranks what needs attention: here, one damaged file, with the restore command. Restoring it from the encrypted backup is on the next slide." |
| 3:40–4:00 | Close | Back to the slides | "Encrypted before it leaves the device, opened only by the named person, refused if changed." |

No terminal is opened on stage. The tampering is done the day before, and the recovery (AC4a) is
shown on a slide with the before-and-after screenshots in
[`screenshots/`](screenshots/) (Modified, the refused download, Admin → Integrity, the agent's
Critical finding, Verified again after restore), not performed live. Which acceptance criterion each
step proves, and the tests behind it, is in [RTM_DEMO_MAP.md](RTM_DEMO_MAP.md); it also says when
registration (AC1) is shown live.

### Preparing the tampered file, the day before

The tool is `backend/scripts/demo_tamper.py`; it runs **on the VPS**, not on the laptop, because
it edits the stored object directly. It only touches accounts whose name starts with `demo-`,
keeps a backup of the original bytes, and refuses a second flip before a restore. Full details in
[TAMPER_DEMO.md](TAMPER_DEMO.md).

1. As `demo-alice`, upload `quarterly-results.txt` (a short readable text file, a few KB) and share
   it with `demo-bob`. As `demo-bob`, download it once to check that it opens.
2. In a terminal: `ssh <server>`, then load the service environment:

   ```bash
   cd /opt/mcs21/current/backend && set -a && . /etc/fyp-secure-file-platform/backend.env && set +a
   ```

3. Get the file id:

   ```bash
   sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA,ENCRYPTED_FILE_DIR PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py list --owner demo-alice
   ```

   It prints every file `demo-alice` owns with its id and status. Copy the id of
   `quarterly-results.txt`.
4. Change one byte:

   ```bash
   sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA,ENCRYPTED_FILE_DIR PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py flip --owner demo-alice --file-id <id>
   ```

   It takes under a second and prints which byte it changed. Run `list` again: the file is now
   marked `TAMPERED`.
5. Keep the `restore` line (the same command with `restore` in place of `flip`) in a text file for
   after the talk.

What happens to the flipped file overnight, so nobody is surprised:

- Nothing restores it by itself. The only way back is `restore`, or `restore_file.py` from a backup,
  both run by hand.
- The daily integrity sweep at 05:30 (Asia/Kuala_Lumpur) will find the changed bytes, record a
  `MODIFIED` check and set the file's status to `CORRUPTED`. From then on Bob's row already reads
  **Modified** when the list opens. That is fine for the talk: the live part is the refused
  download, and the badge stays Modified either way.
- The security agent runs at 06:00 and mails the team's alert address because a Critical finding
  exists. Expect that email on the morning of the talk and ignore it. It is also why step 5 works:
  the same `INTEGRITY_DAMAGE` finding is what the Admin tab shows.
- Do not click the file's status badge or download it as `demo-alice` before the talk; it changes
  nothing important, but the first refusal is better seen by the audience.

After the talk, paste the `restore` command, then as `demo-alice` click the file's **Modified**
badge once. It shows "Checking…" for a few seconds while the server re-hashes the file, then reads
Verified, and the agent finding disappears on the next report.

## The day before

- [ ] Both demo accounts sign in on staging, and `quarterly-results.txt` is shared from Alice to Bob
      and opened once by Bob.
- [ ] `demo_tamper.py flip` has been run on `quarterly-results.txt` and `list` shows it marked
      TAMPERED; the `restore` command is written out with the file id for after the talk.
- [ ] Window A can open Education and the AES-256-GCM card, and `board-minutes.pdf`'s Details
      drawer shows **Access history** for Alice.
- [ ] The administrator window can open Admin → Security agent, and once the file has been refused
      once (or the 05:30 sweep has run) the tab shows the Critical `INTEGRITY_DAMAGE` finding.
- [ ] One full rehearsal, timed. Rehearse the refused download with a second throw-away file,
      or accept that the rehearsal already turns the row Modified; the refusal repeats on every
      download attempt, so the live step still works.
- [ ] The recovery public key on staging is **ACTIVE**: as an administrator, Admin → Recovery key
      shows it; or simply start the rehearsal upload, which fails at once with "The recovery key is
      not active" if it is not. Every upload wraps the file key to that key, so without it nothing
      can be uploaded.
- [ ] `board-minutes.pdf` is a few megabytes at most. The browser reads the whole file into memory,
      encrypts it, decrypts it again to self-check, and only then uploads, so a large file is slow
      on stage for no gain; keep the 500 MiB limit for the slides, not the demo.
- [ ] The backup video is recorded (below) and copied to the presentation laptop.
- [ ] If the demo is run from a local build instead of staging, run `npm ci` in `frontend/` first.
      A `node_modules` from before 2026-10-05 lacks the self-hosted font package and the build fails.
- [ ] Nothing is merged to `main` from two hours before the talk. A merge triggers the automatic
      deploy, which restarts the service for a few seconds.

## The morning of the talk

- [ ] Register a throw-away `demo-carol-<date>` on staging from the presentation laptop. If the email
      code arrives within a minute, AC1 is shown live at the start of the slot; if not, it stays on
      the slide ([RTM_DEMO_MAP.md](RTM_DEMO_MAP.md), "AC1 on the day").
- [ ] The 06:00 Security agent alert email about `quarterly-results.txt` has arrived. That is
      expected; it means the flip is still in place.

## 30 minutes before

- [ ] Health check: `https://secureview.tech/health/live` returns 200.
- [ ] Both windows signed in, with both passphrases at hand. The passphrase is asked for on every
      Download and decrypt and every share (Alice once in step 2, Bob in steps 3 and 4), and the
      key locks again straight after, so there is nothing to unlock in advance.
- [ ] Browser zoom 125 %, notifications and chat apps off, password-manager pop-ups dismissed.
- [ ] `board-minutes.pdf` sits on the desktop; delete any earlier copy from Alice's My Files.
- [ ] Window C is signed in as the administrator with Admin → Security agent already open, so step
      5 is one click.
- [ ] Phone hotspot ready in case the venue network fails.

## If something goes wrong

| Problem | Do |
| --- | --- |
| The network drops or staging does not answer | Switch to the backup video at the same step; it follows this script |
| Unlock or a download hangs for more than ~10 s | Say "this is where it would…", switch to the video for that step |
| The passphrase dialog appears at download or share | Expected every time: type the passphrase and carry on |
| Bob's list does not show the new share or the Modified row | Click the refresh control on the list, or click into the window again; it reloads when it comes to the front |
| The tamper download unexpectedly succeeds | The `flip` was not in place (someone ran `restore`, or `list` shows no TAMPERED mark); show the video's step 4 and the Modified screenshot |
| The Security agent tab shows no Critical finding | The file has not been checked since the flip; it appears after the refused download in step 4, press Refresh on the tab. Otherwise show the screenshot |
| A step was mis-clicked | Do not repair it live; go to the next step |

## The backup video

Recorded: [`media/demo-backup.mp4`](media/demo-backup.mp4) (2 min 23 s, no sound, 1280×720). It follows
this script step by step, labels whose screen is showing (Alice's or Bob's browser), and step 4 really
changes the stored file: the card in the video shows the actual `demo_tamper.py flip` command and its
output, and the file is restored afterwards. Copy it to the presentation laptop and check it plays
without a network. If the presenter talks over it, pause it where needed; it is shorter than the slot
on purpose.

It was made on a disposable local stack running the same code as staging (the recording signs in
automatically, which is only done on a local stack). It was recorded on 2026-10-05, before PR #215, so
the upload screen in it is slightly out of date: the algorithm dropdown has no grades or explanation box,
and the finished upload shows an "Encryption Complete" button instead of the green status. The rest of
the flow is the same as staging today. To re-record after
a UI change, from `frontend/` with a local stack and two local `demo-*` accounts:

```bash
node scripts/record-demo.mjs --base http://localhost:5173 --accounts accounts.json --tamper tamper.sh --out ../docs/presentation/media
```

`tamper.sh` runs `backend/scripts/demo_tamper.py "$@"` with the local stack's environment loaded.
