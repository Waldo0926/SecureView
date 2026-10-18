# Changelog folder / 更改日志目录

Where the team records what it did. There is one active team record; the work-package folder is
kept only so historical evidence remains traceable.

| File | Answers | Who writes it |
| --- | --- | --- |
| [`CHANGELOG.md`](CHANGELOG.md) | What changed in the product, and why it mattered | Everyone |
| [`work-packages/`](work-packages/) | Historical CT package baselines, scope, and limitations | Read-only archive |

## Which one does my entry go in?

Ask what your reader wants to know.

- **Something about the product is now different** — a new endpoint, a fixed defect, a changed
  contract, a deployment that behaves differently. That belongs in `CHANGELOG.md`, under the
  section matching the area, whichever track did the work.
- **A piece of work opened, progressed, or closed** — record the meaningful state change and why
  it matters in `CHANGELOG.md`; update README and TODO too when current capabilities or remaining
  work changed.

Do not create or extend personal or track-specific logs under `work-packages/`. The existing
crypto-track file preserves the original CT evidence and remains available for historical audit.

## Conventions

- Bilingual, English first then 简体中文, as a pair of lines per entry. It matches the rest of
  the repository's documentation.
- Say **why**, not only what. The diff already records what changed; it cannot record the
  reason, and the reason is what a reader six weeks later actually needs.
- Keep historical work-package files unchanged except to correct factual errors or mark archive
  status; do not use them for new activity.
- Nothing here is generated. If an entry is wrong, correct it in place.

## History

This folder replaces `CT_Logs/`, which was named for one track but had become the project's
only changelog. `git log --follow` traces both files back through the move.

---

# 更改日志目录

团队记录做过什么的地方。现在只维护一份团队共享记录；工作包目录仅用于保留可追溯的历史证据。

| 文件 | 回答什么 | 由谁写 |
| --- | --- | --- |
| [`CHANGELOG.md`](CHANGELOG.md) | 产品发生了什么变化，以及为什么重要 | 所有人 |
| [`work-packages/`](work-packages/) | 历史 CT 工作包的基线、范围与限制 | 只读档案 |

## 我的记录该写进哪一份？

想一想读者想知道的是什么。

- **产品现在不一样了**——新增端点、修好的缺陷、变更的契约、行为不同的部署。写进 `CHANGELOG.md`
  对应领域的小节，无论这项工作出自哪条线。
- **某块工作开始、推进或收尾了**——把有意义的状态变化及原因写进 `CHANGELOG.md`；如果当前能力或
  剩余工作改变，也要同步 README 与 TODO。

不要再在 `work-packages/` 下新增或续写个人/分轨日志。现有 crypto-track 文件只用于保留早期 CT
证据，供历史审计查阅。

## 约定

- 双语，英文在前、简体中文在后，每条成对出现，与仓库其余文档保持一致。
- 写清楚**为什么**，而不只是改了什么。diff 已经记录了改动本身，却记录不了当时的理由，而理由正是
  六周后的读者真正需要的东西。
- 历史工作包文件除纠正事实错误或标记归档状态外保持不变，不再记录新活动。
- 这里没有任何自动生成的内容。条目写错了就地改正。

## 沿革

本目录取代了 `CT_Logs/`——那个目录以某一条线命名，却实际上成了整个项目唯一的更改日志。两个文件
都可以用 `git log --follow` 追溯到迁移之前。
