# Frontend

[English](README.md) | [简体中文](README.zh-CN.md)

Vue 3 + TypeScript frontend for SecureView, talking to the FYP backend at `/api/v1`. The
interface uses the "Sealed" style (self-hosted Geist font, green only for verified/sealed, red
only for changed/dangerous), works in light, dark and system themes, and switches between
English and Simplified Chinese from the header or Settings.

## Run

```bash
npm install
npm run dev
```

Backend should be running at `http://localhost:8000`.

## Pages

| Route | Description |
|-------|-------------|
| `/` | Home: hero with real sample bytes, how it works, comparison questions |
| `/how-it-works` | Animated explainer and the seven-step picture guide |
| `/login` | Sign in |
| `/register` | Two-step registration: the account (email, code, login password), then the encryption passphrase; offers the private key file once |
| `/forgot-password` | Email-code login-password reset |
| `/dashboard` | Signed-in workspace with a getting-started checklist |
| `/upload` | File encryption upload with the live encryption steps and byte comparison (auth required) |
| `/files` | My Files: owned and shared files, folders, details panel, share, revoke, access history, encrypted preview (auth required) |
| `/audit-logs` | Activity Log: account activity first, then file access records (auth required) |
| `/profile` | Profile and avatar (auth required) |
| `/settings` | Theme, language, key fingerprint, login-password change, passphrase change with the current one, passphrase reset with the private key file, account deletion (auth required) |
| `/admin` | Role-aware operations: overview statistics, users (details, enable/disable, temporary login password), files, integrity, security agent, audit chain, recovery requests, recovery key |
| `/education` | Education articles and algorithm explorer |
| `/help` | Help: animated explainer, walkthrough videos of the real product, picture guide |
| `/team` | Contact us: feedback form, supervisor and team |
| `/benchmark/argon2` | Argon2id timing benchmark for this device |
| anything else | Not-found page |

The round button at the bottom right of every page opens the Help assistant
([docs/HELP_ASSISTANT.md](../docs/HELP_ASSISTANT.md)).

## Structure

- `src/pages/`, `src/components/` — pages and UI components (`securfile/` holds the public site sections)
- `src/api/` — Axios clients aligned with backend `/api/v1`
- `src/crypto/` — file encryption/decryption (six AEAD suites), sharing-key rewrap, key
  fingerprints, private-key-file unlock and passphrase reset
- `src/stores/` — Pinia auth/file state
- `src/i18n/`, `src/locales/` — English and Simplified Chinese ([docs/I18N.md](../docs/I18N.md))
- `src/composables/useTheme.ts` — System/light/dark theme
- `scripts/layout-audit.mjs`, `scripts/text-audit.mjs` — scripted layout and text checks across
  pages, widths, themes and languages

The browser implements account-key enrolment, passphrase/private-key-file unlock, passphrase
reset with the private key file, encrypted upload, authenticated download/decryption, sharing
with recipient key-fingerprint confirmation, revocation, folders, search, audit history,
refresh rotation, server-revoking logout, account deletion, and role-aware
admin/recovery/audit operations on `/admin`. Settings also changes the passphrase with the
current one (#201). Successor-key rotation exists in the API but has no UI yet.

On `/files`, **Download and decrypt** opens the unlock dialog when needed and saves the
original file. The **Encrypted preview** panel shows the stored bytes and offers **Download
encrypted file**, which saves the ciphertext as `<filename>.ciphertext` without unlocking the
account key. Both use the authenticated, integrity-checked `POST /files/{file_id}/download`
endpoint. Encrypted downloads contain only the stored blob, not a complete
offline-decryption envelope.

## Environment

The default API base is already `http://localhost:8000/api/v1`. To override it, create an
untracked `frontend/.env.local`:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```
