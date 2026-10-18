# Requirements to demo map

[简体中文](RTM_DEMO_MAP.zh-CN.md)

Every acceptance criterion in [PROPOSAL_TRACEABILITY.md](../PROPOSAL_TRACEABILITY.md) and where the
audience sees it during the presentation. Step numbers refer to [DEMO_SCRIPT.md](DEMO_SCRIPT.md).
"On screen" is what the assessor actually sees, which is the evidence; "Test evidence" is the
automated check behind it.

| AC | Requirement | Where in the talk | On screen (evidence) | Test evidence |
| --- | --- | --- | --- | --- |
| AC1 | Registration with a protected RSA private key | Live only if the registration email arrives in the morning test (see below); otherwise the key-custody slide | Live: the verification code arrives, the passphrase step, then "Save Your Private Key" with the key shown once. Slide: the same screen as a screenshot, plus the line "the server only stores the key sealed under your passphrase" | `backend/tests/unit/test_auth_service.py`, `backend/tests/integration/test_auth_mysql.py`; every browser spec registers through the real page (`frontend/browser-tests/golden-path.browser.ts`) |
| AC2 | Choice of algorithm, only ciphertext uploaded | Step 1, Upload | The algorithm list (six suites), the four timed stages, and the byte comparison: the file starts `%PDF`, what the server receives is random-looking | `frontend/src/crypto/upload.integration.test.ts`, `frontend/src/crypto/primitives.test.ts` (known-answer vectors), `backend/tests/unit/test_crypto_vectors.py`; golden-path browser spec |
| AC3 | Recipient decrypts with their own passphrase | Steps 2 and 3, Share and Open | Alice sees Bob's key fingerprint before sharing and Bob's Settings shows the same value; Bob types his own passphrase and the PDF opens | `frontend/src/e2e/live-stack.integration.test.ts` shares, decrypts and revokes under all six suites against a real API and MySQL; `frontend/src/crypto/share.test.ts`, `share-confirm.test.ts` |
| AC4 | Tampered file refused before decryption | Step 4, Tamper | Bob presses download on `quarterly-results.txt` (flipped the day before): "The encrypted file could not be verified", the row reads **Modified**, nothing is saved | `frontend/browser-tests/tamper-visibility.browser.ts`; the `tamper-drill` CI job flips a byte on every merge and checks the server refuses it |
| AC4a | Recovery after tampering | Slide after the demo | Screenshots in `docs/presentation/screenshots/`: the Modified row, the refused download, Admin → Integrity listing the damaged file, the Security agent's Critical finding, the row back to Verified after restore, Admin → Integrity clean again | `backend/tests/unit/test_restore_file.py`, the restore drill step in `mysql-gate`, the restore step of `tamper-visibility.browser.ts` |
| AC5 | Timestamped audit of who did what | Step 3b, Audit | Alice opens the shared file's access history: Bob's download with his name and the time, next to her own upload and share | `backend/tests/unit/test_audit_log_service.py`, `test_audit_checkpoint.py`, `backend/tests/integration/test_file_lifecycle_mysql.py`; `frontend/src/utils/audit-trail.test.ts` |
| AC6 | Interactive crypto education | Opening of the demo, a few seconds | Window A starts on Education with an algorithm card open while the scene is set | `frontend/browser-tests/language-switch.browser.ts` and `mobile-public-pages.browser.ts` open `/education` in both languages and at phone width |
| AC7 | Dismissible four-stage progress pipeline | During step 1 | The four stages tick off with their real timings, then the receipt is closed with its close button | `frontend/browser-tests/golden-path.browser.ts` checks the receipt stays until closed (#200); `frontend/src/crypto/upload.test.ts` |
| AC8 | AI agent for a defined automation problem | Step 5, The agent saw it | Admin → Security agent: a **Critical** `INTEGRITY_DAMAGE` finding naming `quarterly-results.txt`, with the restore command as the recommended action | `backend/tests/unit/test_security_agent_rules.py`, `test_security_agent_service.py`, `backend/tests/integration/test_security_agent_mysql.py` |

## AC1 on the day

Registration needs the emailed verification code. On the morning of the talk, register a throw-away
`demo-carol-<date>` on staging from the presentation laptop:

- If the code arrives within a minute, register live at the start of the demo slot (about 40 s; the
  closing line is then said over the Security agent screen instead of on its own).
- If it does not arrive, do not try on stage. Show the "Save Your Private Key" screenshot on the
  key-custody slide and say what it proves: the key pair is made in the browser and the server only
  ever stores the private key sealed under the passphrase.

## Which agent rule fires

The tamper step is caught by the Security agent rule `INTEGRITY_DAMAGE`
(`backend/app/services/security_agent_rules.py`): any file whose newest integrity check is
`MODIFIED`, `MISSING` or `ERROR`, or whose status is `CORRUPTED`. `MODIFIED` is **Critical**. The
refused download in step 4 records a `MODIFIED` check, so the finding is there as soon as the
administrator presses **Run analysis**; the 05:30 sweep and the 06:00 daily report find it on their
own overnight (that is the alert email expected on the morning of the talk).
