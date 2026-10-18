# Homepage walkthrough screenshots

English | [简体中文](README.zh-CN.md)

Each image exists twice: `<name>.webp` in English and `<name>-zh.webp` in Simplified Chinese; the home page shows the set for the language chosen in the header. These WebP files show the real Vue interface in Light mode with fictitious accounts
(`sam`, `alex`) and `Project notes.txt`. Blue outlines and numbers identify the controls.
Mobile crops show the relevant upload column or the narrower real file-list layout.
Share and Unlock dialogs also have dedicated `*-mobile.webp` captures (same modal crop at
a phone-width viewport). The screenshots contain no real credentials or user files.

To refresh them after a UI change:

1. Run `npm run build` in `frontend`.
2. Run `node scripts/capture-workflow.cjs <module-directory> [browser-executable]`.
   The module directory must contain Playwright and Sharp; the optional executable can
   point to a local Chromium browser. Use the available workspace runtime.
3. Inspect all images, then rebuild so the refreshed assets are included in `dist`.

The script serves the local build and intercepts API calls in a disposable browser
context. Upload encryption runs in the browser with ephemeral example public keys,
but backend results and the recipient list are fixtures. The example account key is
sealed with the app's own `sealAccountKey` (loaded through `jiti`), so the Unlock dialog
really opens it, and the Share step stops at the recipient confirmation with its key
fingerprint. The script takes both languages from the same page state (it switches the interface language in place, so open dialogs and tabs stay as they are) and finds the upload and file cards by `data-testid` (`encrypt-card`, `files-card`), not by class names. Last refreshed 2026-10-05, after the "Sealed" redesign and the P1-P3 layout fixes.
This captures UI states;
it is not an end-to-end backend sharing or decryption test.

The home slideshow is in `src/components/securfile/workflow-section.vue`; text and
image mapping are in `src/data/workflow-guide.ts`. The Help page's videos are separate:
see `../videos/README.md`.
