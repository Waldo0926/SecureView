/**
 * The "how SecureView protects a file" story, scene by scene.
 *
 * One source for the animated explainer (`SecurityStory.vue`) and the recorded explainer video,
 * so the captions a viewer reads and what the animation shows cannot drift apart. Every claim
 * here is what the product actually does; `docs/SECURITY_FLOWS.md` is the technical version.
 */

export interface StoryScene {
  /** Stable id, also used by the animation to decide what is on stage. */
  id: 'pick' | 'encrypt' | 'wrap' | 'upload' | 'share' | 'open' | 'tamper'
  title: string
  body: string
  /** The advantage this step gives the user, in one line. */
  why: string
}

export const STORY_SCENES: StoryScene[] = [
  {
    id: 'pick',
    title: 'Alice picks a file',
    body: 'She chooses a file in her own browser. At this point it exists only on her computer.',
    why: 'Nothing has been sent anywhere yet.',
  },
  {
    id: 'encrypt',
    title: 'It is encrypted in her browser',
    body:
      'The browser makes a brand-new random key for this one file and encrypts it with AES-256-GCM ' +
      '(or another authenticated cipher she chose). The readable file never leaves her computer.',
    why: 'Encryption happens before upload, so there is no moment when the server holds the real file.',
  },
  {
    id: 'wrap',
    title: 'The file key is locked as well',
    body:
      'The file key is sealed with Alice’s public key (RSA-OAEP), which only her passphrase can open. ' +
      'A second sealed copy goes to the organisation’s recovery key, which is kept offline.',
    why: 'Losing the server’s data does not give away a single file key.',
  },
  {
    id: 'upload',
    title: 'Only scrambled data reaches the server',
    body:
      'The server stores the ciphertext and the sealed keys, plus a SHA-256 fingerprint. Someone who ' +
      'broke into the server, or an administrator, would see only random-looking bytes.',
    why: 'A server breach exposes no file contents. This is the core difference from ordinary cloud storage.',
  },
  {
    id: 'share',
    title: 'Sharing re-seals the key, not the file',
    body:
      'To share with Bob, Alice’s browser opens her sealed key and seals the same key again with Bob’s ' +
      'public key. The encrypted file is not copied and the server still never sees a key.',
    why: 'Sharing gives one named account access, and can be revoked. There is no public link to leak.',
  },
  {
    id: 'open',
    title: 'Bob opens it with his own passphrase',
    body:
      'Bob’s browser unlocks his copy of the key with his passphrase, decrypts the file, and checks it ' +
      'against its authentication tag before saving it.',
    why: 'Each person uses their own secret. Nobody has to send a password to anyone.',
  },
  {
    id: 'tamper',
    title: 'Tampering is caught, and the original can come back',
    body:
      'If even one stored byte is changed, decryption fails and the download is refused. A daily scan ' +
      'also compares every file with its fingerprint, and an administrator restores the original from ' +
      'the encrypted backup.',
    why: 'You are never silently handed a modified file.',
  },
]

/** The advantages, for the comparison section: ordinary cloud storage versus SecureView. */
/**
 * How long a scene stays up before the explainer moves on by itself.
 *
 * A fixed 7 s felt slow in the supervisor meeting: most viewers had read the caption and were
 * waiting. Each scene now gets 3 s, plus a little for captions longer than the short first one,
 * so the longest stays about 3.5 s. Anyone who wants longer presses Pause.
 */
export const SCENE_BASE_MS = 3000
export const SCENE_MAX_MS = 3500
const SHORT_CAPTION_CHARS = 150
const MS_PER_EXTRA_CHAR = 3

export function sceneDuration(scene: StoryScene): number {
  const chars = scene.title.length + scene.body.length + scene.why.length
  const extra = Math.max(0, chars - SHORT_CAPTION_CHARS) * MS_PER_EXTRA_CHAR
  return Math.min(SCENE_MAX_MS, SCENE_BASE_MS + extra)
}

export interface Comparison {
  question: string
  ordinary: string
  secureview: string
}

export const COMPARISON: Comparison[] = [
  {
    question: 'Who can read your file on the server?',
    ordinary: 'Usually the provider can, and so can anyone who gets into its systems.',
    secureview: 'No one. The server only holds ciphertext it has no key for.',
  },
  {
    question: 'What does a database breach expose?',
    ordinary: 'Usually the files themselves.',
    secureview: 'Random-looking bytes and sealed keys that need each user’s passphrase.',
  },
  {
    question: 'How is a file shared?',
    ordinary: 'A link that works for whoever has it.',
    secureview: 'The key is re-sealed for one named account; access can be revoked.',
  },
  {
    question: 'Would you notice if a stored file changed?',
    ordinary: 'Rarely.',
    secureview: 'Yes. Decryption fails on a single changed byte, and a daily scan checks every file.',
  },
  {
    question: 'Can you see who opened it?',
    ordinary: 'Sometimes, in a log the provider can edit.',
    secureview: 'Every upload, share and download is in a hash-chained audit log that shows any edit.',
  },
]
