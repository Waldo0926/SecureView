# Help-page videos

English | [简体中文](README.zh-CN.md)

Recorded from the real product, not mocked, by `frontend/scripts/record-walkthroughs.mjs`:

| File | What it shows |
| --- | --- |
| `how-it-works.mp4` | The animated explainer (`/how-it-works?present`), seven scenes at eight seconds each. All three are 1920×1080 since 2026-10-14, with a light caption bar |
| `encrypt-upload.mp4` | Sign in, choose a file, the six ciphers with their grades and what two of them are good at, where Education explains more, Start Encryption, the timed encryption steps and byte comparison, the encrypted preview |
| `share-open.mp4` | Share with another account after checking their key fingerprint, that account decrypts it with its own passphrase, then files it in a folder of its own |

Each has a `.jpg` poster. The accounts are made up (`sam`, `alex`, `@example.com`) on a disposable
local stack; passwords and passphrases are masked by the page and were throwaway values.
All three were re-recorded on 2026-10-05 after the "Sealed" redesign (sidebar, centred headers, two-column Settings, the new sign-in page). `encrypt-upload.mp4` and `share-open.mp4` were recorded again on 2026-10-10 after PR #215: the sign-in page shows the 2026-10-09 load-test figures, the algorithm list shows each suite's grade and the explanation box, the finished upload is the green "Encryption Complete" status rather than a button, and Details is a button in Actions. `how-it-works.mp4` is unchanged: the explainer's scenes have not changed, and it was recorded in present mode at eight seconds a scene (the page itself now moves on after about three). The captions are English; the videos have no sound. The caption, outline and sign-in helpers are shared with the
presentation's backup video in `frontend/scripts/lib/video.mjs`.

To re-record after a UI change, start a local stack (API, MySQL, `npx vite`), seed two accounts with
`backend/scripts/seed_test_account.py`, put their credentials in a JSON file
`{ "sam": {username, password, passphrase}, "alex": {...} }`, then from `frontend/`:

```bash
node scripts/record-walkthroughs.mjs --base http://localhost:5173 --accounts accounts.json --out public/videos
```

`--only encrypt-upload,share-open` re-records just those. `share-open` expects the file that
`encrypt-upload` uploads. Needs ffmpeg on PATH. Check the result frame by frame before committing.
