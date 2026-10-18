/**
 * The Help page's videos, recorded from the real product by `scripts/record-walkthroughs.mjs`
 * against a local stack with made-up accounts (Sam and Alex). The captions are burned into the
 * video; the same steps are listed under it as text, for anyone who cannot watch or hear it.
 *
 * A data file rather than part of `SoftwareGuide.vue` so the Help assistant can link to one video
 * (`/help?video=<id>#videos`) and its tests can check that the id exists.
 */
export interface HelpVideo {
  id: string
  tag: string
  title: string
  summary: string
  videoSrc: string
  poster: string
  steps: string[]
}

export const HELP_VIDEOS: HelpVideo[] = [
  {
    id: 'how-it-works',
    tag: 'Animation',
    title: 'What happens to your file',
    summary: 'One file followed from Alice to Bob: encrypted in the browser, stored as noise, shared, opened, and protected from tampering.',
    videoSrc: '/videos/how-it-works.mp4',
    poster: '/videos/how-it-works.jpg',
    steps: [
      'Alice picks a file; it is still only on her computer.',
      'Her browser encrypts it with a new random key.',
      'The key is sealed with her public key, plus an offline recovery copy.',
      'Only ciphertext and sealed keys reach the server.',
      'Sharing re-seals the key for Bob; the file is not copied.',
      'Bob opens it with his own passphrase, and it is verified.',
      'A changed byte is caught and the original is restored from backup.',
    ],
  },
  {
    id: 'encrypt-upload',
    tag: 'Walkthrough',
    title: 'Encrypt & upload a file',
    summary: 'Sign in, choose a file, pick the cipher, and encrypt it in the browser so only ciphertext is uploaded.',
    videoSrc: '/videos/encrypt-upload.mp4',
    poster: '/videos/encrypt-upload.jpg',
    steps: [
      'Sign in with your password (it only signs you in).',
      'Open Upload and choose a file.',
      'Keep AES-256-GCM or pick another of the six ciphers; each shows a grade, and the box below explains the one chosen.',
      'Press Start Encryption: the file is encrypted before it is sent.',
      'When it is done, Encryption Complete is a green status, not a button: the file is already uploaded.',
      'In My Files the sizes match — the tag is stored separately.',
      'Encrypted preview shows what the server holds: random-looking bytes.',
    ],
  },
  {
    id: 'share-access',
    tag: 'Walkthrough',
    title: 'Share securely with another account',
    summary: 'Share with a named account by re-sealing the key, then see the recipient decrypt it with their own passphrase and file it in a folder of their own.',
    videoSrc: '/videos/share-open.mp4',
    poster: '/videos/share-open.jpg',
    steps: [
      'In My Files, press Share on the file.',
      'Unlock your key with your encryption passphrase (it stays in the browser).',
      'Enter the recipient’s username and press Share.',
      'The recipient signs in and finds it under Shared with me.',
      'Download and decrypt, with the recipient’s own passphrase.',
      'The tag and SHA-256 match, so it is exactly the uploaded file.',
      'The recipient files it in a private folder; the owner’s folders are unaffected.',
    ],
  },
]
