# Help assistant（帮助助手）

每个页面右下角的圆形按钮会打开 **Help assistant**（Issue #146）。它回答“怎么做……”“它是怎么工作的……”
以及“为什么不用 Google Drive / WhatsApp / 邮件……”这类问题，给出简短摘要、操作类问题的编号步骤，以及指向
产品内页面的链接。

界面上一律叫 Help assistant，不叫 agent 或 AI：项目里的 agent 是安全 Agent（Admin → Security agent），
名称要把两者区分开。

从 v2（Issue #148）起，它还能回答已登录用户关于自己账户的问题，例如 “who has access to budget.xlsx?”
“what has been shared with me?”。见下文[关于自己账户的问题](#关于自己账户的问题v2)。

## 如何作答

不使用大语言模型，匹配问题时也不发起任何网络请求，全部在访客的浏览器里完成：

1. 先规范化问题：转小写、去标点、做轻量词干化（share/shared/sharing 归为一词）、合并同义词
   （send → share、lost → forgot、e2e → end-to-end），内容里从未出现的词会被纠正为最接近的已有词
   （允许一处拼写错误，长词允许两处）。
2. 用 BM25 给助手知道的每条答案打分。与某条意图的示例问句共有的相邻词对会略微加分，逐字问出示例问句则加分更多。
3. 显示得分最高的答案，并把接下来两条放在 “Was this not it?” 里。如果最高分过低，或答案覆盖的问题权重不到一半，
   就回答 “I'm not sure”，列出最接近的三条，并链接 Help 和 Contact us。

答案来源（按优先级）：

| 来源 | 文件 | 链接到 |
| --- | --- | --- |
| 人工整理的意图 | `frontend/src/data/assistant/intents.ts` | 各自的链接 |
| 知识库文章 | `frontend/src/data/education/knowledge.ts` | `/education?article=<id>#article-<id>` |
| 算法页面 | `frontend/src/data/education/algorithms.ts` | `/education?algorithm=<id>#algorithm-detail` |
| 讲解动画场景与对比 | `frontend/src/data/security-story.ts` | `/how-it-works` |
| 图文引导步骤 | `frontend/src/data/workflow-guide.ts` | `/#how-it-works` |

这些来源是直接读取而不是复制，所以修改 Education 文章就会改变助手的回答。匹配逻辑在
`frontend/src/utils/assistant-search.ts`，是一个纯函数模块，旁边有单元测试。

问题不会保存到任何服务器，也不会被记录。面板只在 `sessionStorage` 里记住是否打开以及最近五个问题，关闭标签页即清除；退出登录时也会清除。

## 关于自己账户的问题（v2）

七项只读检查根据访客自己的文件和记录作答，逻辑在 `frontend/src/utils/assistant-account.ts`，
结果由 `AccountCheckCard.vue` 显示在面板里。

| 检查 | 典型问法 | 读取的内容 |
| --- | --- | --- |
| `overview` | “What is in my account?” | `GET /files`（总数）、`GET /files/folders` |
| `who-has-access` | “Who has access to budget.xlsx?” | `GET /files?scope=mine&search=`、`GET /files/{id}/shared-users` |
| `file-activity` | “When was budget.xlsx last downloaded?” | `GET /files?scope=mine&search=`、`GET /audit-logs/file/{id}` |
| `my-shares` | “Which of my files have I shared?” | 最新的 50 个自己的文件，逐个查 `shared-users` |
| `shared-with-me` | “What has been shared with me?” | `GET /files?scope=shared`，以及本浏览器尚未展示过的文件 |
| `modified-files` | “Are any of my files marked Modified?” | 逐页读取 `GET /files`（最多 500 个文件）的 `status` 字段 |
| `recent-activity` | “Any failed sign-ins?” | `GET /audit-logs?limit=50` |

遵守的规则：

- **只读。** 任何检查都不修改数据。需要采取行动时（撤销、恢复、改密码），只给出去对应页面操作的链接。
- **不超出页面本身能看到的。** 每项检查都用 My Files 和 Activity Log 已有的请求，在访客自己的会话下发出，
  服务器的归属规则原样生效。`who-has-access` 和 `file-activity` 只查看访客自己的文件，因为只有文件所有者才能列出接收者、
  查看完整历史。
- **问题仍然不会发出去。** 最多只把文件名交给 `GET /files?search=`，也就是 My Files 搜索框本来就会发的请求。
  结果不保存：页面打开期间只留在内存里，所以关掉再打开面板不会重复查询；刷新后答案会停在一个按钮后面，不会自动再向服务器查询。
- **问了才查。** 关于账户的问题（“who has access to my file?”）会立即检查。附带检查的一般性问题
  （“who downloaded my file?” 也可能是在问“怎么查”）先显示一般回答，再给一个按钮，例如
  *Check one of my files' history*。未登录时，账户类问题会说明检查能看到什么，并提示先登录。

问题里的文件名会在匹配前取出：引号里的内容，或带扩展名的单词（`report.pdf`）。两者都没有时，
帮助内容里从未出现的词会被当作文件名（“who has access to my thesis draft” → “thesis draft”），
但仅限明显在问自己文件的问题。搜索先用完整名称，再按词从长到短逐个尝试；匹配到多个或零个时，给出一个短的文件列表供选择。

`/files?q=<名称>&tab=shared` 会在对应标签页打开 My Files 并搜索该名称，账户类回答里的链接都用它。

## 新增一条意图

在 `frontend/src/data/assistant/intents.ts` 的 `ASSISTANT_INTENTS` 中加一条（字段说明见英文版
[HELP_ASSISTANT.md](HELP_ASSISTANT.md) 的示例）：`id` 唯一；`group` 为 `using` / `how` / `compare` / `account`；
`phrasings` 至少三种真实问法；`summary` 二到四句、能独立回答问题；操作类问题写 `steps`，控件名称与界面一致；
`links` 一到三个产品内链接；可选的 `check` 指定这条回答能提供的账户检查。`account` 组意图的摘要以
“Signed in, …” 开头：这是未登录访客看到的内容，不能读起来像已经查过了。

然后运行 `cd frontend && npx vitest run src/utils/assistant-search.test.ts`。以下情况测试会失败：

- 该意图的任一问法（或标题）匹配到别的答案：给 `keywords` 补词，或者改写那条其实属于别的问题的问法；
- 链接不是真实的路由、锚点、文章、算法或视频；
- 摘要不是二到四句，或没有产品链接、产品链接超过三个。

问题里常用而内容里没有的词，可以加到 `assistant-search.ts` 的 `SYNONYMS`。同时在测试的 “realistic questions”
列表里加一条真实问法（可以带拼写错误）。

### 对比类回答

`compare` 组的意图对其他产品的每一项说法，都要用 `kind: 'source'` 链接到该产品自己的文档，测试只接受列出的来源域名。
只说有什么不同，不说 SecureView “更安全”，并在回答里保留它的局限（接收者已下载的副本仍在对方手里）。

## 依赖的深链接

- `/help?video=<id>#videos`：在 Help 页打开对应视频（`frontend/src/data/help-videos.ts`）。
- `/education?article=<id>#article-<id>`：在知识库打开对应文章。
- `/education?algorithm=<id>#algorithm-detail`：在算法浏览器打开对应算法。

## 本版本不包含

服务端改写层（例如只把检索到的答案文本交给智谱 `glm-4-flash`）在 v2 时考虑过但没有做，因为它会把访客的问题发给第三方。
账户检查从不代替访客执行操作（不能在面板里撤销或删除）。语言切换（#74）上线后，意图文本也会成为可翻译字符串。
