/**
 * The Help assistant's curated answers (Issue #146).
 *
 * One entry per question people actually ask: how to use SecureView, how it works, and how it
 * differs from tools they already know. The matcher in `utils/assistant-search.ts` scores a
 * question against each entry's `title`, `phrasings` and `keywords`, alongside the Education
 * articles, the explainer and the picture guide, so an article answers anything not listed here.
 *
 * Rules for the text, because a help answer that is wrong is worse than none:
 * - Every step names the control as the interface labels it (Start Encryption, Share, Revoke).
 * - Every internal link is a real route, anchor, article, algorithm or video; a unit test checks.
 * - Comparisons state only what the linked source says, and never claim SecureView is "more
 *   secure" in general: they say what is different, including what SecureView cannot do.
 *
 * How to add an entry: docs/HELP_ASSISTANT.md.
 */

export type IntentGroup = 'using' | 'how' | 'compare' | 'account'

/**
 * A read-only look at the signed-in visitor's own account (v2), run in `utils/assistant-account.ts`
 * with the same requests My Files and the Activity Log already make.
 */
export type AccountCheckId =
  | 'overview'
  | 'who-has-access'
  | 'my-shares'
  | 'shared-with-me'
  | 'modified-files'
  | 'file-activity'
  | 'recent-activity'

export interface AssistantLink {
  label: string
  /** A path inside SecureView (`/files`, `/help?video=…#videos`) or an https source. */
  to: string
  /** `video` gets a play icon; `source` marks a citation outside SecureView. */
  kind?: 'page' | 'video' | 'source'
}

export interface AssistantIntent {
  id: string
  group: IntentGroup
  /** The question as a chip or a "did you mean" choice shows it. */
  title: string
  /** Ways people phrase it. Each one must find this intent (unit-tested). */
  phrasings: string[]
  /** Extra words that point here but read badly as a question. */
  keywords: string[]
  /** Two to four sentences. */
  summary: string
  steps?: string[]
  /** One to three links into the product, plus sources for comparisons. */
  links: AssistantLink[]
  /**
   * The account check this answer can run for someone signed in. An `account` intent runs it as
   * soon as it is the answer; any other intent offers it behind a button, because the question
   * may have been a general one.
   */
  check?: AccountCheckId
}

const HELP = { label: 'Help and videos', to: '/help' }
const VIDEO_ENCRYPT = { label: 'Video: encrypt and upload', to: '/help?video=encrypt-upload#videos', kind: 'video' } as const
const VIDEO_SHARE = { label: 'Video: share and open', to: '/help?video=share-access#videos', kind: 'video' } as const
const VIDEO_STORY = { label: 'Video: what happens to your file', to: '/help?video=how-it-works#videos', kind: 'video' } as const

export const ASSISTANT_INTENTS: AssistantIntent[] = [
  // ---------------------------------------------------------------- Using it
  {
    id: 'get-started',
    group: 'using',
    title: 'How do I create an account?',
    phrasings: [
      'how do I create an account',
      'how do I sign up',
      'how to register',
      'I am new, where do I start',
      'what do I need to get started',
    ],
    keywords: ['register', 'signup', 'account', 'new', 'start', 'begin', 'join'],
    summary:
      'Register with a username, a login password, an encryption passphrase and your email address. ' +
      'Your browser then creates your keys and shows a private key file once: download it and keep it ' +
      'somewhere safe, because it is the only way back if you forget the passphrase.',
    steps: [
      'Open Register and fill in your username, password and email.',
      'Press Send code, type in the code from your email, and press Next.',
      'Choose an encryption passphrase, different from your password, and press Register.',
      'On Save Your Private Key, download the .pem file and tick that you have saved it.',
      'Press Continue to your workspace: you are already signed in.',
    ],
    links: [
      { label: 'Register', to: '/register' },
      { label: 'Quick start', to: '/how-it-works#start-heading' },
    ],
  },
  {
    id: 'upload-encrypt',
    group: 'using',
    title: 'How do I upload and encrypt a file?',
    phrasings: [
      'how do I upload a file',
      'how do I encrypt a file',
      'how to upload and encrypt',
      'where do I add a new file',
      'how do I protect a document',
      'how do I add my first file',
    ],
    keywords: ['upload', 'encrypt', 'add', 'select', 'drag', 'start', 'protect', 'store', 'save'],
    summary:
      'Uploading and encrypting are one step. Your browser encrypts the file with a new random key ' +
      'before anything is sent, so only ciphertext reaches the server. Files can be up to 500 MB.',
    steps: [
      'Sign in and open Upload.',
      'Press Select Files (or drag a file onto the box).',
      'Keep AES-256-GCM, the default, unless you have a reason to pick another cipher.',
      'Press Start Encryption and keep the tab open until Encryption Complete appears.',
      'Press View Encrypted Files to see it in My Files.',
    ],
    links: [{ label: 'Upload', to: '/upload' }, VIDEO_ENCRYPT, { label: 'Picture guide', to: '/#how-it-works' }],
  },
  {
    id: 'share',
    group: 'using',
    title: 'How do I share a file?',
    phrasings: [
      'how do I share a file',
      'how do I send a file to someone',
      'how can my teammate get my file',
      'give a colleague access to a document',
      'can I share with a friend',
      'how to share securely',
      'can I make a public link',
      'how does sharing work',
    ],
    keywords: ['share', 'recipient', 'teammate', 'colleague', 'friend', 'someone', 'person', 'access', 'collaborate', 'link', 'public'],
    summary:
      'You share with a named SecureView account, not with a link. Your browser re-seals the file’s key ' +
      'with the recipient’s public key; they open it with their own passphrase, never yours. They need ' +
      'their own account first.',
    steps: [
      'Open My Files and find a file you own.',
      'Press its black Share button, next to Delete.',
      'If asked, unlock with your encryption passphrase.',
      'Enter their exact username or email address and press Share.',
      'Check the name and key fingerprint shown, then press Confirm and share.',
      'They sign in and find it under My Files → Shared with me.',
    ],
    links: [{ label: 'My Files', to: '/files' }, VIDEO_SHARE],
  },
  {
    id: 'revoke',
    group: 'using',
    title: 'How do I stop sharing a file?',
    phrasings: [
      'how do I revoke access',
      'how do I stop sharing a file',
      'unshare a file',
      'remove someone from a shared file',
      'take back access I gave',
      'I shared with the wrong person',
    ],
    keywords: ['revoke', 'stop', 'remove', 'unshare', 'cancel', 'undo', 'wrong', 'withdraw'],
    summary:
      'Open the file’s Share window and press Revoke beside the person. They lose access straight away ' +
      'and the file leaves their list. Revoking cannot reach a copy they already downloaded and decrypted.',
    steps: [
      'Open My Files and press Share on the file.',
      'Under Currently shared with, press Revoke beside their name.',
      'Confirm Revoke access.',
    ],
    check: 'who-has-access',
    links: [
      { label: 'My Files', to: '/files' },
      { label: 'See who opened it', to: '/audit-logs' },
    ],
  },
  {
    id: 'download-decrypt',
    group: 'using',
    title: 'How do I download and open a file?',
    phrasings: [
      'how do I download a file',
      'how do I decrypt a file',
      'how do I open a file shared with me',
      'get my original file back',
      'where do I find a file someone shared with me',
      'the download is unreadable',
    ],
    keywords: ['download', 'decrypt', 'open', 'read', 'view', 'get', 'retrieve', 'find', 'received', 'ciphertext', 'unreadable'],
    summary:
      'Use Download and decrypt: your browser unlocks the file’s key with your own passphrase, decrypts it ' +
      'and checks its authentication tag before saving the original. Download encrypted file saves the ' +
      'scrambled .ciphertext instead, which is not readable.',
    steps: [
      'Open My Files (files shared with you are under Shared with me).',
      'Press Download and decrypt (the down arrow) on the file.',
      'If asked, unlock with your own encryption passphrase.',
      'The original file is saved to your device.',
    ],
    links: [{ label: 'My Files', to: '/files' }, VIDEO_SHARE],
  },
  {
    id: 'passphrase-vs-password',
    group: 'using',
    title: 'Password or passphrase: what is the difference?',
    phrasings: [
      'what is the difference between the password and the passphrase',
      'why do I need two passwords',
      'is the passphrase the same as my password',
      'which secret do I type where',
      'what is the encryption passphrase for',
    ],
    keywords: ['passphrase', 'password', 'difference', 'two', 'both', 'secret', 'login', 'unlock'],
    summary:
      'Your password signs you in and can be reset by email. Your encryption passphrase unlocks your ' +
      'files in the browser; SecureView never sees it and cannot reset it for you. Use different ones, ' +
      'and keep your private key file: it lets you set a new passphrase yourself.',
    links: [
      { label: 'Two secrets, two jobs', to: '/how-it-works#start-heading' },
      { label: 'Settings', to: '/settings' },
    ],
  },
  {
    id: 'forgot-passphrase',
    group: 'using',
    title: 'I forgot my encryption passphrase',
    phrasings: [
      'I forgot my encryption passphrase',
      'I lost my passphrase',
      'reset my passphrase',
      'cannot unlock my files',
      'my passphrase does not work',
      'change my encryption passphrase',
      'can you recover my files if I forget everything',
    ],
    keywords: ['forgot', 'passphrase', 'reset', 'change', 'unlock', 'key', 'pem', 'locked', 'recover'],
    summary:
      'Use the private key file (.pem) you saved when you registered: in Settings it sets a new passphrase, ' +
      'and your files and shares stay as they are. Without that file nobody can open your files — not ' +
      'the team, not the server — and a recovery request cannot bring back a passphrase.',
    steps: [
      'Find the secureview-private-key-….pem file you downloaded at registration.',
      'Open Settings and go to Forgot your encryption passphrase?',
      'Choose the key file, type a new passphrase twice and tick the confirmation.',
      'Press Reset passphrase. (To open one file now, Unlock with your private key file works too.)',
    ],
    links: [
      { label: 'Settings', to: '/settings' },
      { label: 'Two secrets, two jobs', to: '/how-it-works#start-heading' },
    ],
  },
  {
    id: 'forgot-password',
    group: 'using',
    title: 'I forgot my login password',
    phrasings: [
      'I forgot my password',
      'I cannot sign in',
      'reset my login password',
      'I am locked out of my account',
      'change my password',
    ],
    keywords: ['forgot', 'password', 'reset', 'login', 'signin', 'locked', 'email', 'code'],
    summary:
      'Reset it with your username, your email address and a code we email you. This changes only the ' +
      'login password: your encryption passphrase and private key are untouched, so your files stay ' +
      'accessible.',
    steps: [
      'On the sign-in page press Forgot password?',
      'Enter your username and email, then press Send code.',
      'Type in the code from your email and choose a new password.',
      'Sign in with the new password.',
    ],
    links: [
      { label: 'Reset password', to: '/forgot-password' },
      { label: 'Sign in', to: '/login' },
    ],
  },
  {
    id: 'private-key-file',
    group: 'using',
    title: 'What is the private key file for?',
    phrasings: [
      'what is the private key file',
      'what is the pem file I downloaded',
      'do I need to keep the key file',
      'where is my private key',
      'I lost my private key file',
    ],
    keywords: ['private', 'key', 'file', 'pem', 'backup', 'keep', 'safe', 'download'],
    summary:
      'It is your account’s private key, shown once when you register. It opens your files without the ' +
      'passphrase and lets you set a new passphrase in Settings. It is read in your browser and never ' +
      'uploaded. Keep it offline and private: anyone who has it can open your files.',
    links: [
      { label: 'Settings', to: '/settings' },
      { label: 'Public and private keys', to: '/education?article=public-private-keys#article-public-private-keys' },
    ],
  },
  {
    id: 'folders',
    group: 'using',
    title: 'How do I use folders?',
    phrasings: [
      'how do I make a folder',
      'how do I organise my files',
      'move a file into a folder',
      'can I put shared files in a folder',
      'delete a folder',
    ],
    keywords: ['folder', 'organise', 'organize', 'move', 'sort', 'group', 'rename', 'directory'],
    summary:
      'Folders only organise the list; the encrypted file itself does not move. Your folders are private, ' +
      'so filing a file someone shared with you does not change where its owner keeps it. Sharing is ' +
      'per file, not per folder. Deleting a folder keeps its files, which become No folder.',
    steps: [
      'In My Files, type a name under Folders and press Add.',
      'Choose the folder in the file’s Folder menu to file it.',
      'Use the pencil to rename a folder and the bin to delete it.',
    ],
    links: [{ label: 'My Files', to: '/files' }],
  },
  {
    id: 'verified-status',
    group: 'using',
    title: 'What does “Verified” mean?',
    phrasings: [
      'what does verified mean',
      'what does the status column mean',
      'my file says modified',
      'what does pending mean',
      'is my file ok',
    ],
    keywords: ['verified', 'status', 'badge', 'modified', 'pending', 'ok', 'healthy', 'integrity', 'check'],
    summary:
      'The Status badge in My Files says whether the stored ciphertext is still the file you uploaded. ' +
      'Verified means it is active and no check has found it changed. Modified means a download failed ' +
      'its authentication check or the daily scan found the bytes no longer match their SHA-256 ' +
      'fingerprint; it will not decrypt, and an administrator can restore it from the encrypted backup.',
    check: 'modified-files',
    links: [
      { label: 'My Files', to: '/files' },
      { label: 'Hashing and integrity', to: '/education?article=hashing-vs-encryption#article-hashing-vs-encryption' },
    ],
  },
  {
    id: 'encrypted-preview',
    group: 'using',
    title: 'What is the encrypted preview?',
    phrasings: [
      'what is the encrypted preview',
      'can I see what the server stores',
      'prove my file is encrypted',
      'show me the ciphertext',
      'how do I check my file is really encrypted',
    ],
    keywords: ['preview', 'ciphertext', 'stored', 'bytes', 'hex', 'prove', 'evidence', 'see', 'really'],
    summary:
      'Under each file name in My Files, Encrypted preview shows the start of what the server stores: ' +
      'random-looking bytes, the stored size and the SHA-256 recorded at upload. It also checks that the ' +
      'original file type’s header is not visible. Nothing in it is decrypted.',
    steps: [
      'Open My Files.',
      'Press Encrypted preview under the file name.',
      'For the whole thing, open More (⋯) on the file, choose Download encrypted file, and open it in a hex viewer.',
    ],
    links: [{ label: 'My Files', to: '/files' }, VIDEO_ENCRYPT],
  },
  {
    id: 'delete-file',
    group: 'using',
    title: 'How do I delete a file?',
    phrasings: ['how do I delete a file', 'remove a file I uploaded', 'get rid of a file', 'erase my upload'],
    keywords: ['delete', 'remove', 'erase', 'bin', 'trash', 'file'],
    summary:
      'Press the red Delete icon on a file you own and confirm. The encrypted file is removed and every ' +
      'share is revoked at once. It cannot be undone from the app.',
    steps: ['Open My Files.', 'Press Delete (the red bin) on the file.', 'Confirm Delete file.'],
    links: [{ label: 'My Files', to: '/files' }],
  },
  {
    id: 'delete-account',
    group: 'using',
    title: 'How do I delete my account?',
    phrasings: ['how do I delete my account', 'close my account', 'remove my account and data', 'I want to leave SecureView'],
    keywords: ['delete', 'account', 'close', 'remove', 'leave', 'erase', 'data'],
    summary:
      'Settings → Delete account removes the account and every file you uploaded, including files you ' +
      'shared. Nobody can bring them back afterwards. If you are only locked out by a forgotten ' +
      'passphrase, reset it with your private key file instead.',
    steps: [
      'Open Settings and press Delete account.',
      'Enter your login password and type DELETE.',
      'Press Delete my account.',
    ],
    links: [{ label: 'Settings', to: '/settings' }],
  },
  {
    id: 'file-size',
    group: 'using',
    title: 'How large a file can I upload?',
    phrasings: [
      'how large a file can I upload',
      'what is the maximum file size',
      'how big can files be',
      'can I upload several files at once',
      'my large upload failed',
    ],
    keywords: ['size', 'limit', 'maximum', 'max', 'big', 'large', 'mb', 'gb', 'multiple', 'several', 'many'],
    summary:
      'Each file can be up to 500 MB, and you can choose several at once. Encrypting needs about four ' +
      'times the file’s size in memory, so a very large file may fail on a phone or with many tabs open.',
    links: [{ label: 'Upload', to: '/upload' }],
  },
  {
    id: 'phone',
    group: 'using',
    title: 'Does it work on my phone?',
    phrasings: ['does it work on my phone', 'can I use it on mobile', 'is there an app for my phone', 'use it on an iPad or tablet'],
    keywords: ['phone', 'mobile', 'iphone', 'android', 'tablet', 'ipad', 'browser'],
    summary:
      'Yes, in the phone’s web browser; there is nothing to install. Everything works the same, with My ' +
      'Files shown as cards. Very large files may not encrypt on a phone because of its memory.',
    links: [
      { label: 'Upload', to: '/upload' },
      { label: 'My Files', to: '/files' },
    ],
  },
  {
    id: 'sign-out',
    group: 'using',
    title: 'How do I sign out?',
    phrasings: ['how do I sign out', 'how to log out', 'logout', 'end my session'],
    keywords: ['logout', 'signout', 'exit', 'session', 'leave'],
    summary:
      'Open the account menu (your initials, top right) and press Log out; Settings has the same button. ' +
      'Signing out also forgets your unlocked key in this browser, so the next person cannot open your files.',
    links: [{ label: 'Settings', to: '/settings' }],
  },
  {
    id: 'appearance',
    group: 'using',
    title: 'How do I switch to dark mode?',
    phrasings: ['how do I switch to dark mode', 'change the theme', 'light mode', 'the screen is too bright'],
    keywords: ['dark', 'light', 'theme', 'mode', 'appearance', 'colour', 'color', 'bright'],
    summary:
      'Use the Theme menu in the header (or Theme in the account menu) to pick Light, Dark or System. ' +
      'Settings → Appearance does the same, and the choice is remembered on this device.',
    links: [{ label: 'Settings', to: '/settings' }],
  },
  {
    id: 'contact',
    group: 'using',
    title: 'How do I contact the team?',
    phrasings: ['how do I contact support', 'who do I talk to about a problem', 'report a bug', 'send feedback'],
    keywords: ['contact', 'support', 'team', 'feedback', 'bug', 'problem', 'report', 'issue', 'talk'],
    summary:
      'Contact us has a feedback form that opens a ready-to-send email in your own mail app, plus the team ' +
      'and supervisor. Never include your passphrase or private key file in a message.',
    links: [{ label: 'Contact us', to: '/team' }],
  },
  {
    id: 'recovery-request',
    group: 'using',
    title: 'What is Request recovery?',
    phrasings: [
      'what does request recovery do',
      'what is a recovery request',
      'a file will not open with my key',
      'can an administrator recover my file',
    ],
    keywords: ['recovery', 'request', 'officer', 'administrator', 'admin', 'restore', 'rewrap'],
    summary:
      'Every file key also has a sealed copy for the organisation’s recovery key, kept offline. If one ' +
      'file’s key cannot be opened with your current account key, Request recovery asks a recovery ' +
      'officer to re-seal it to your key. It never reveals or resets your passphrase.',
    steps: [
      'In My Files, open More (⋯) on the file and choose Request recovery.',
      'Give a reason and press Submit request.',
      'Follow it under Recovery in the menu.',
    ],
    links: [
      { label: 'My Files', to: '/files' },
      { label: 'Recovery requests', to: '/admin' },
    ],
  },

  // ---------------------------------------------------------------- How it works
  {
    id: 'end-to-end',
    group: 'how',
    title: 'What does end-to-end encryption mean here?',
    phrasings: [
      'what does end to end encryption mean',
      'is it end to end encrypted',
      'how does SecureView work',
      'how is my file protected',
      'explain how it works',
    ],
    keywords: ['endtoend', 'e2ee', 'work', 'protect', 'secure', 'safe', 'private', 'how'],
    summary:
      'Your file is encrypted in your browser before upload and decrypted in the recipient’s browser after ' +
      'download. In between — in transit and on the server — it exists only as ciphertext, and the keys ' +
      'that open it are sealed so that only your and your recipients’ passphrases unlock them.',
    links: [{ label: 'How it works', to: '/how-it-works' }, VIDEO_STORY],
  },
  {
    id: 'server-cannot-read',
    group: 'how',
    title: 'Can SecureView or an admin read my files?',
    phrasings: [
      'can the server read my files',
      'can an admin see my files',
      'what if SecureView gets hacked',
      'what does a breach expose',
      'can the team open my documents',
      'who can see my files',
    ],
    keywords: ['server', 'admin', 'administrator', 'breach', 'hack', 'hacked', 'read', 'see', 'team', 'trust'],
    summary:
      'No. The server stores ciphertext and file keys sealed with users’ public keys; it never receives a ' +
      'readable file, a file key or your passphrase. A breach or an administrator would see random-looking ' +
      'bytes. The one other sealed copy is for the organisation’s recovery key, which is kept offline.',
    links: [
      { label: 'Why a breach exposes nothing', to: '/how-it-works' },
      { label: 'Encrypted preview', to: '/files' },
    ],
  },
  {
    id: 'same-size',
    group: 'how',
    title: 'Why is the encrypted file the same size?',
    phrasings: [
      'why is the encrypted file the same size',
      'the encrypted size equals the original size',
      'should encryption not make the file bigger',
      'why are original and encrypted sizes identical',
    ],
    keywords: ['size', 'same', 'bigger', 'larger', 'equal', 'identical', 'bytes', 'padding', 'tag'],
    summary:
      'Every cipher SecureView offers is a stream-style authenticated cipher: it does not pad, so the ' +
      'ciphertext is exactly as long as the original. The nonce and the 16-byte authentication tag are ' +
      'stored next to it rather than inside it.',
    links: [
      { label: 'Which encryption should I choose?', to: '/education?article=choosing-a-cipher#article-choosing-a-cipher' },
      { label: 'My Files', to: '/files' },
    ],
  },
  {
    id: 'which-cipher',
    group: 'how',
    title: 'Which encryption should I choose?',
    phrasings: [
      'which encryption should I choose',
      'which cipher is best',
      'AES or ChaCha',
      'what is AES-256-GCM',
      'should I change the default algorithm',
    ],
    keywords: ['cipher', 'algorithm', 'aes', 'chacha', 'xchacha', 'gcm', 'siv', 'choose', 'best', 'default', 'option'],
    summary:
      'Keep AES-256-GCM, the default, unless you have a reason. All six choices are authenticated ' +
      'encryption and detect tampering, and each file gets a new random key, so a repeated nonce cannot ' +
      'happen here. The recipient does not need to know which you picked.',
    links: [
      { label: 'Which encryption should I choose?', to: '/education?article=choosing-a-cipher#article-choosing-a-cipher' },
      { label: 'AES-256 explained', to: '/education?algorithm=aes256#algorithm-detail' },
    ],
  },
  {
    id: 'tamper',
    group: 'how',
    title: 'What happens if a file is tampered with?',
    phrasings: [
      'what if someone changes my file',
      'what happens if a file is tampered with',
      'how do I know the file was not modified',
      'can someone alter my file on the server',
      'is the file corrupted',
    ],
    keywords: ['tamper', 'tampered', 'change', 'alter', 'modify', 'modified', 'corrupt', 'integrity', 'restore'],
    summary:
      'Change even one stored byte and decryption fails, so the download is refused rather than handing you ' +
      'a modified file. A daily scan also compares every file with its SHA-256 fingerprint, and an ' +
      'administrator can restore the original from the encrypted backup.',
    check: 'modified-files',
    links: [{ label: 'How it works', to: '/how-it-works' }, VIDEO_STORY],
  },
  {
    id: 'access-records',
    group: 'how',
    title: 'What does the Activity Log show?',
    phrasings: [
      'who opened my file',
      'can I see who downloaded my file',
      'what are access records',
      'what is the activity log',
      'where is the audit log',
      'can someone edit the log',
    ],
    keywords: ['access', 'records', 'audit', 'log', 'history', 'who', 'opened', 'downloaded', 'activity', 'chain'],
    summary:
      'Activity Log lists your own account activity (sign-ins, passphrase and key changes) and every ' +
      'upload, share and download, including what the people you shared with did. The log is ' +
      'hash-chained, so an edited or deleted entry breaks the chain and the page says so. ' +
      'For one file, press Access history in My Files.',
    check: 'file-activity',
    links: [
      { label: 'Activity Log', to: '/audit-logs' },
      { label: 'My Files', to: '/files' },
    ],
  },

  // ---------------------------------------------------------------- Comparisons
  {
    id: 'vs-google-drive',
    group: 'compare',
    title: 'Why not just use Google Drive?',
    phrasings: [
      'why not just use Google Drive',
      'how is this different from Google Drive',
      'is Google Drive encrypted',
      'SecureView vs Google Drive',
      'compared with OneDrive or Dropbox',
    ],
    keywords: ['google', 'drive', 'gdrive', 'cloud', 'dropbox', 'onedrive', 'icloud', 'difference', 'compare', 'versus'],
    summary:
      'Google Drive encrypts files in transit and at rest, but for ordinary accounts Google manages the ' +
      'keys. Client-side encryption, where the organisation holds the keys, exists only on some paid ' +
      'Workspace editions. In SecureView you hold the key, you share with a named account and can revoke ' +
      'it, and every access is in a tamper-evident log. A recipient still keeps any copy they downloaded.',
    links: [
      { label: 'Ordinary cloud storage vs SecureView', to: '/how-it-works#why-heading' },
      { label: 'Google Drive: how Drive protects your privacy', to: 'https://support.google.com/drive/answer/10375054', kind: 'source' },
      { label: 'Google: default encryption at rest, with keys Google manages', to: 'https://docs.cloud.google.com/docs/security/encryption/default-encryption', kind: 'source' },
      { label: 'Google Workspace: client-side encryption editions', to: 'https://knowledge.workspace.google.com/admin/security/about-client-side-encryption', kind: 'source' },
    ],
  },
  {
    id: 'vs-whatsapp',
    group: 'compare',
    title: 'Why not just send it on WhatsApp?',
    phrasings: [
      'why not just send it on WhatsApp',
      'is WhatsApp not end to end encrypted too',
      'SecureView vs WhatsApp',
      'how is this different from WhatsApp',
      'compared with Signal or Telegram',
    ],
    keywords: ['whatsapp', 'signal', 'telegram', 'messenger', 'chat', 'message', 'difference', 'compare', 'versus'],
    summary:
      'WhatsApp messages and attachments are end-to-end encrypted with the Signal protocol, so the ' +
      'difference is not secrecy. It is about files: sharing is per chat, there is no per-file revoke or ' +
      'per-file access history, files have a size cap, and backups are end-to-end encrypted only if you ' +
      'turn that on. SecureView keeps a file under your key with named, revocable access and a ' +
      'tamper-evident log; a recipient still keeps any copy they downloaded.',
    links: [
      { label: 'Revoke a share', to: '/files' },
      { label: 'WhatsApp: end-to-end encryption', to: 'https://blog.whatsapp.com/end-to-end-encryption', kind: 'source' },
      { label: 'Signal: WhatsApp’s Signal Protocol integration', to: 'https://signal.org/blog/whatsapp-complete/', kind: 'source' },
      { label: 'WhatsApp: 2 GB file sharing', to: 'https://blog.whatsapp.com/reactions-2gb-file-sharing-512-groups', kind: 'source' },
      { label: 'WhatsApp: turning on encrypted backups', to: 'https://blog.whatsapp.com/encrypting-your-whatsapp-chat-backup-just-got-easier', kind: 'source' },
    ],
  },
  {
    id: 'vs-email',
    group: 'compare',
    title: 'Why not just email the file?',
    phrasings: [
      'why not just email the file',
      'is email attachment secure',
      'SecureView vs email',
      'can I not just send it as an attachment',
      'how is this different from Gmail',
    ],
    keywords: ['email', 'mail', 'gmail', 'outlook', 'attachment', 'attach', 'difference', 'compare', 'versus'],
    summary:
      'Ordinary email is protected in transit with TLS only when both mail providers support it, and the ' +
      'attachment is then stored by the providers, who can read it unless you use something like S/MIME. ' +
      'Once sent it cannot be withdrawn. In SecureView the file stays ciphertext under keys only you and ' +
      'your named recipients can open, and you can revoke their access later.',
    links: [
      { label: 'Share a file', to: '/files' },
      { label: 'Gmail: how Gmail encrypts your email', to: 'https://support.google.com/mail/answer/6330403', kind: 'source' },
    ],
  },

  // ---------------------------------------------------------------- Your account (v2)
  // Signed in, these run their check at once and answer from the visitor's own files and records.
  // Signed out, the summary says what the check would show and the panel asks them to sign in.
  {
    id: 'account-overview',
    group: 'account',
    title: 'What is in my account?',
    phrasings: [
      'what is in my account',
      'how many files do I have',
      'give me a summary of my account',
      'how many files have I uploaded',
    ],
    keywords: ['account', 'summary', 'overview', 'many', 'count', 'total', 'number', 'uploaded'],
    summary:
      'Signed in, I can count your own files, the files shared with you, your folders and any ' +
      'shared files you have not opened the list for yet. Nothing is changed by looking.',
    links: [{ label: 'My Files', to: '/files' }],
    check: 'overview',
  },
  {
    id: 'account-who-has-access',
    group: 'account',
    title: 'Who has access to one of my files?',
    phrasings: [
      'who has access to my file',
      'who did I share this file with',
      'who else has access to it',
      'list the people who have access',
    ],
    keywords: ['access', 'people', 'recipients', 'else', 'currently', 'right', 'now'],
    summary:
      'Signed in, name the file (or pick it from your newest ones) and I will list everyone who has ' +
      'access to it now, with the date each person was added. Revoking someone is done from its Share window.',
    links: [{ label: 'My Files', to: '/files' }],
    check: 'who-has-access',
  },
  {
    id: 'account-file-activity',
    group: 'account',
    title: 'What has happened to one of my files?',
    phrasings: [
      'what has happened to my file',
      'show the history of my file',
      'when was my file last downloaded',
      'how many times was my file downloaded',
    ],
    keywords: ['history', 'happened', 'times', 'timeline'],
    summary:
      'Signed in, name one of your files and I will summarise its access history: who downloaded it, ' +
      'when it was shared or revoked, and any failed integrity check. Access history in My Files shows the full list.',
    links: [
      { label: 'Activity Log', to: '/audit-logs' },
      { label: 'My Files', to: '/files' },
    ],
    check: 'file-activity',
  },
  {
    id: 'account-my-shares',
    group: 'account',
    title: 'Which of my files have I shared?',
    phrasings: [
      'which of my files have I shared',
      'what have I shared',
      'list everything I shared with other people',
      'show the files I gave other people access to',
    ],
    keywords: ['which', 'shared', 'list', 'everything', 'others', 'gave', 'outgoing'],
    summary:
      'Signed in, I go through your newest files and list each one that someone else can open, with ' +
      'their names. It is the same list each file’s Share window shows.',
    links: [{ label: 'My Files', to: '/files' }],
    check: 'my-shares',
  },
  {
    id: 'account-shared-with-me',
    group: 'account',
    title: 'What has been shared with me?',
    phrasings: [
      'what has been shared with me',
      'did anyone send me a file',
      'did someone share a file with me',
      'any new files for me',
      'show the files other people shared with me',
      'what did I receive',
    ],
    keywords: ['received', 'receive', 'incoming', 'new', 'me', 'anyone', 'inbox', 'for'],
    summary:
      'Signed in, I list the newest files other people have shared with you and who shared each one. ' +
      'Files you have not seen since you last opened the Shared with me tab are marked new.',
    links: [{ label: 'Shared with me', to: '/files?tab=shared' }],
    check: 'shared-with-me',
  },
  {
    id: 'account-modified-files',
    group: 'account',
    title: 'Are any of my files marked Modified?',
    phrasings: [
      'are any of my files marked modified',
      'check all my files for tampering',
      'scan my files for problems',
      'have any of my files been damaged',
    ],
    keywords: ['any', 'all', 'scan', 'problem', 'problems', 'damaged', 'broken', 'tampering', 'marked'],
    summary:
      'Signed in, I look at the Status of every file you can open and list any marked Modified. ' +
      'The server sets that when a download fails its authentication check or the daily scan finds ' +
      'the stored bytes changed; an administrator can restore the file from the encrypted backup.',
    links: [{ label: 'My Files', to: '/files' }],
    check: 'modified-files',
  },
  {
    id: 'account-recent-activity',
    group: 'account',
    title: 'What happened on my account recently?',
    phrasings: [
      'what happened on my account recently',
      'show my recent activity',
      'has anyone tried to log into my account',
      'any failed sign ins on my account',
      'any failed logins',
    ],
    keywords: ['recent', 'recently', 'lately', 'happened', 'tried', 'failed', 'attempts', 'suspicious', 'account'],
    summary:
      'Signed in, I show the latest events on your account and your files from the Activity Log, and ' +
      'point out failed sign-ins. If one was not you, change your password.',
    links: [
      { label: 'Activity Log', to: '/audit-logs' },
      { label: 'Settings', to: '/settings' },
    ],
    check: 'recent-activity',
  },
]

/** The chips a fresh panel offers: one per common need, in the order a newcomer meets them. */
export const SUGGESTED_INTENT_IDS = [
  'upload-encrypt',
  'share',
  'forgot-passphrase',
  'passphrase-vs-password',
  'vs-google-drive',
  'vs-whatsapp',
] as const

/** Offered as well once someone is signed in: questions about their own account. */
export const ACCOUNT_SUGGESTED_INTENT_IDS = [
  'account-shared-with-me',
  'account-who-has-access',
  'account-recent-activity',
] as const

/** Where every fallback points. */
export const FALLBACK_LINKS: AssistantLink[] = [HELP, { label: 'Contact us', to: '/team' }]
