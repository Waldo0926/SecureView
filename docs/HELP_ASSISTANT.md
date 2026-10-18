# Help assistant

The round button at the bottom right of every page opens the **Help assistant** (Issue #146).
It answers "how do I…", "how does it work…" and "why not Google Drive / WhatsApp / email…"
with a short summary, numbered steps for a how-to, and links into the product.

It is called the Help assistant everywhere, never an agent or AI: the security agent
(Admin → Security agent) is the project's agent, and the names keep the two apart.

Since v2 (Issue #148) it also answers questions about the signed-in visitor's own account, such as
"who has access to budget.xlsx?" or "what has been shared with me?". See
[Questions about your own account](#questions-about-your-own-account-v2).

## How it answers

There is no language model, and matching a question makes no network call. Everything runs in
the visitor's browser:

1. The question is normalised: lowercased, punctuation stripped, a light stemmer
   (share/shared/sharing meet), synonyms folded together (send → share, lost → forgot,
   e2e → end-to-end), and a word the content never uses is corrected to the nearest one it
   does (one typo, two in a long word).
2. It is scored with BM25 against every answer the assistant knows. A word pair that also
   appears in one of an intent's sample questions adds a little, and asking one of those
   questions word for word adds more.
3. The best answer is shown with the next two as "Was this not it?". If the best score is
   low, or the answer shares less than half of the question's weight, the reply is
   "I'm not sure" with the closest three and links to Help and Contact us.

The answers come from, in this order of preference:

| Source | File | Linked to |
| --- | --- | --- |
| Curated intents | `frontend/src/data/assistant/intents.ts` | their own links |
| Knowledge articles | `frontend/src/data/education/knowledge.ts` | `/education?article=<id>#article-<id>` |
| Algorithm pages | `frontend/src/data/education/algorithms.ts` | `/education?algorithm=<id>#algorithm-detail` |
| Explainer scenes and comparison | `frontend/src/data/security-story.ts` | `/how-it-works` |
| Picture guide steps | `frontend/src/data/workflow-guide.ts` | `/#how-it-works` |

The sources are read, not copied, so editing an Education article changes what the assistant
says. The matcher is `frontend/src/utils/assistant-search.ts`, a pure module with unit tests
beside it.

Questions are not stored on any server or logged. The panel remembers whether it was open and
the last five questions in `sessionStorage`, which ends with the tab. Signing out clears them.

## Questions about your own account (v2)

Seven read-only checks answer from the visitor's own files and records. They live in
`frontend/src/utils/assistant-account.ts`, and `AccountCheckCard.vue` shows the result in the panel.

| Check | Asked as | What it reads |
| --- | --- | --- |
| `overview` | "What is in my account?" | `GET /files` (totals), `GET /files/folders` |
| `who-has-access` | "Who has access to budget.xlsx?" | `GET /files?scope=mine&search=`, `GET /files/{id}/shared-users` |
| `file-activity` | "When was budget.xlsx last downloaded?" | `GET /files?scope=mine&search=`, `GET /audit-logs/file/{id}` |
| `my-shares` | "Which of my files have I shared?" | the 50 newest own files, and `shared-users` for each |
| `shared-with-me` | "What has been shared with me?" | `GET /files?scope=shared`, and which ones this browser has not shown yet |
| `modified-files` | "Are any of my files marked Modified?" | `GET /files` page by page (up to 500 files), the `status` field |
| `recent-activity` | "Any failed sign-ins?" | `GET /audit-logs?limit=50` |

The rules they keep:

- **Read-only.** No check changes anything. Where the answer suggests an action (revoke, restore,
  change the password) it links to the page where the visitor does it.
- **No more than the pages show.** Each check uses the requests My Files and the Activity Log
  already make, under the visitor's own session, so the server's ownership rules apply unchanged.
  `who-has-access` and `file-activity` only look at the visitor's own files, because only an owner
  may list a file's recipients or read its whole history.
- **The question is still not sent.** At most a file name goes to `GET /files?search=`, the same
  search the My Files box runs. Results are never stored: they stay in memory while the page is
  open, so closing and reopening the panel does not ask again, and after a reload the answer waits
  behind a button.
- **Run when asked.** A question about the account ("who has access to my file?") runs its check
  at once. A general question with a check attached ("who downloaded my file?" could mean "how
  would I find out?") shows the general answer and a button such as *Check one of my files'
  history*. Signed out, an account question says what the check would show and asks the visitor
  to sign in.

A file name in a question is taken out before matching: anything in quotes, or one word with an
extension (`report.pdf`). Without either, the words the help content never uses are taken as the
name ("who has access to my thesis draft" → "thesis draft"), but only when the question is
plainly about the visitor's own file. The search tries the whole name, then each word, longest
first; several matches or none become a short list of files to pick from.

`/files?q=<name>&tab=shared` opens My Files on that tab, searched for that name. The links in
account answers use it.

## Adding an intent

Add an entry to `ASSISTANT_INTENTS` in `frontend/src/data/assistant/intents.ts`:

```ts
{
  id: 'export-files',              // unique, kebab-case
  group: 'using',                  // 'using' | 'how' | 'compare' | 'account'
  title: 'Can I download all my files at once?',
  phrasings: [                     // at least three ways people actually ask it
    'can I download all my files at once',
    'export everything',
    'bulk download',
  ],
  keywords: ['export', 'bulk', 'all', 'everything', 'zip'],
  summary: 'Two to four sentences that answer the question on their own.',
  steps: ['Only when it is a how-to.', 'Name each control as the interface labels it.'],
  links: [{ label: 'My Files', to: '/files' }],   // one to three product links
  check: 'my-shares',              // optional: the account check this answer can offer
},
```

An `account` intent's summary starts with "Signed in, …": it is what a signed-out visitor sees, and
it must not read as if the check had already run.

Then run `cd frontend && npx vitest run src/utils/assistant-search.test.ts`. The tests fail if:

- any of the intent's phrasings (or its title) finds a different answer: add words to
  `keywords`, or reword a phrasing that is really a different question;
- a link is not a real route, anchor, article, algorithm or video;
- the summary is not two to four sentences, or there are no product links or more than three.

A word the questions use but the content does not can be taught in `SYNONYMS` in
`assistant-search.ts`. Add a realistic question for it to the "realistic questions" list in
the test, typos included.

### Comparisons

An intent in the `compare` group must cite every claim it makes about another product with a
`kind: 'source'` link to that product's own documentation, and the test only accepts sources on
the hosts it lists. Say what is different, never that SecureView is "more secure", and keep its
limits in the answer (a recipient keeps a copy they already downloaded).

## Deep links it relies on

- `/help?video=<id>#videos` opens the Help page on that video (`frontend/src/data/help-videos.ts`).
- `/education?article=<id>#article-<id>` opens the Knowledge Base on that article.
- `/education?algorithm=<id>#algorithm-detail` opens the Algorithm Explorer on that algorithm.

## Not in this version

A server-side rewording layer (for example Zhipu `glm-4-flash`, fed only the retrieved answer
text) was considered for v2 and not built, because it would send the visitor's question to a third
party. Account checks never act on the visitor's behalf (no revoking or deleting from the panel).
When the language switch (#74) lands, the intents become translatable strings too.
