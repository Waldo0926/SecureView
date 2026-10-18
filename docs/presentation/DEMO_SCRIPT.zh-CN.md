# 4 分钟现场演示脚本

[English](DEMO_SCRIPT.md)

演示时段是 12 分钟展示里的 3:30–7:30（[TALKING_POINTS.zh-CN.md](TALKING_POINTS.zh-CN.md) 第 0 节）。
目标是让观众记住三件事：文件离开浏览器之前就已经加密；只有指定的人能打开；文件被改动就会被拒绝。
全部在 staging（`https://secureview.tech`）上进行。

## 角色与准备

| 角色 | 位置 | 登录账号 |
| --- | --- | --- |
| 演讲者（“Alice”） | 浏览器窗口 A，屏幕左半边 | `demo-alice` |
| 同事（“Bob”） | 浏览器窗口 B，屏幕右半边，**使用另一个浏览器用户配置**，两个会话互不干扰 | `demo-bob` |
| 管理员 | 浏览器窗口 C，第三个用户配置，预先打开 Admin → Security agent，第 5 步之前最小化 | 团队在 staging 上的 ADMIN 账号 |

`demo-alice` 和 `demo-bob` 已经在 staging 上建好（2026-10-04 用种子脚本创建，不需要邮箱验证码；登录密码 `<demo-password>`，
passphrase 由项目负责人保管）。用户名必须以 `demo-` 开头，因为篡改工具会拒绝其他账号。两个账号的口令要互不相同，也不要和任何真实
账号相同。

展示前，用 `demo-alice` 上传 `quarterly-results.txt`（一个简短、能直接看懂的文本文件），分享给 `demo-bob`，然后在服务器上用
`demo_tamper.py flip` 把它改掉一个字节（具体步骤见下面“前一天准备被篡改的文件”）。这样现场 Bob 有两个共享文件：现场上传的
`board-minutes.pdf` 能打开，`quarterly-results.txt` 会被拒绝。演示过程中不用终端。

## 脚本

| 时间 | 步骤 | 操作 | 讲解 |
| --- | --- | --- | --- |
| 0:00–0:15 | 交代场景 | 窗口 A 事先停在 **Education**，打开 AES-256-GCM 卡片（AC6）；先指一下它，再指两个窗口 | “这个应用做的每件事这里都有讲解，还有可以动手试的 playground。Alice 要把一份机密报告发给 Bob。他们俩都不信任服务器，你们也不应该信任。” |
| 0:15–1:05 | **1. 上传** | 窗口 A：Upload → 选择 `board-minutes.pdf`，算法保持 **AES-256-GCM · 最高 · 推荐**（下面的说明框会解释原因）→ Start Encryption，让四个阶段播完（AC7）。按钮会变成绿色的 **Encryption Complete** 状态条，不能再点，所以不会重复上传。然后用关闭按钮关掉回执 | “你看到的每一步耗时都是真实测出来的：在浏览器里用一把新密钥加密，再把这把密钥包装起来，然后上传。看这些字节：原文件开头是 `%PDF`，服务器收到的是一堆乱码。” |
| 1:05–1:45 | **2. 分享** | 窗口 A：My Files → `board-minutes.pdf` → Share → 在弹出的口令框里输入 Alice 的口令 → 输入 `demo-bob` → Share。确认页显示 Bob 的密钥指纹 → **Confirm and share**。窗口 B：Settings 里显示同一个指纹 | “发送之前，Alice 能看到文件会被锁到哪一把密钥上。Bob 从自己的设置页读出指纹：两边一致，所以只有 Bob 能打开。服务器从头到尾没拿到过这把密钥。”然后点 Confirm and share |
| 1:45–2:20 | **3. 打开** | 窗口 B：My Files → Shared with me → `board-minutes.pdf` → 点下载图标（鼠标悬停显示 **Download and decrypt**）。每次都会弹出口令框，输入 Bob 的口令。打开保存下来的文件 | “Bob 用的是他自己的口令，不是 Alice 的。文件取出时先校验，再在他自己的设备上解密。”“他的密钥是用口令封住的，所以每次下载浏览器都会问，用完马上重新锁上。” |
| 2:20–2:45 | **3b. 审计** | 窗口 A：My Files → `board-minutes.pdf` → Details → **Access history** | “Alice 能看到谁在什么时候打开过它：她自己的上传、分享，还有 Bob 几秒钟前的下载。每条记录都和前一条串成哈希链，所以日志本身也没法被悄悄改掉。” |
| 2:45–3:15 | **4. 篡改** | 还在窗口 B 的 Shared with me。指一下 `quarterly-results.txt`，这是 Alice 分享的第二个文件，上台前已经在服务器上被改过（准备步骤见下）。点它的下载图标，输入 Bob 的口令 | “昨晚这个文件在服务器磁盘上被改了一个字节，管理员或者入侵者都做得到。Bob 来取它。”下载被拒绝，提示 “The encrypted file could not be verified”，列表下方出现红色提示，这一行变成 **Modified**，什么都没有保存。“改过了，所以被拒绝。不需要任何人相信我们。” |
| 3:15–3:40 | **5. 代理看到了** | 窗口 C（管理员）：Admin → **Security agent**。最上面一条是 **Critical** 的 `INTEGRITY_DAMAGE`，点名 `quarterly-results.txt` | “管理员不用自己去发现。安全代理每天读审计日志和完整性检查，把需要处理的事排好序：这里是一个损坏的文件，连恢复命令都给出来了。从加密备份恢复它在下一页幻灯片。” |
| 3:40–4:00 | 收尾 | 切回幻灯片 | “离开设备前就加密，只有指定的人能打开，被改动就拒绝。” |

现场不开终端。篡改在前一天做好，恢复（AC4a）用 [`screenshots/`](screenshots/) 里恢复前后的截图在幻灯片上讲（Modified、被拒绝的下载、
Admin → Integrity、代理的 Critical 发现、恢复后重新 Verified），不现场做。每一步证明哪条验收标准、背后有哪些测试，见
[RTM_DEMO_MAP.zh-CN.md](RTM_DEMO_MAP.zh-CN.md)；注册（AC1）什么时候现场演示也写在那里。

### 前一天准备被篡改的文件

工具是 `backend/scripts/demo_tamper.py`，它**在 VPS 上**跑，不是在演示电脑上，因为它直接改存储的对象。它只碰用户名以 `demo-` 开头的账号，
会备份原始字节，并且在 restore 之前拒绝第二次 flip。完整说明见 [TAMPER_DEMO.zh-CN.md](TAMPER_DEMO.zh-CN.md)。

1. 用 `demo-alice` 上传 `quarterly-results.txt`（几 KB 的短文本文件，能直接看懂），分享给 `demo-bob`。用 `demo-bob` 下载一次，确认能打开。
2. 终端里 `ssh <server>`，然后加载服务环境：

   ```bash
   cd /opt/mcs21/current/backend && set -a && . /etc/fyp-secure-file-platform/backend.env && set +a
   ```

3. 查文件 id：

   ```bash
   sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA,ENCRYPTED_FILE_DIR PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py list --owner demo-alice
   ```

   它列出 `demo-alice` 名下所有文件的 id 和状态。复制 `quarterly-results.txt` 的 id。
4. 改一个字节：

   ```bash
   sudo -u fypapp --preserve-env=DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASSWORD,DB_SSL_CA,ENCRYPTED_FILE_DIR PYTHONPATH=$PWD .venv/bin/python scripts/demo_tamper.py flip --owner demo-alice --file-id <id>
   ```

   不到一秒跑完，打印改了哪个字节。再跑一次 `list`，这个文件已经标着 `TAMPERED`。
5. 把 `restore` 那行（同一条命令，`flip` 换成 `restore`）存在文本文件里，讲完用。

翻过字节的文件过夜会发生什么，提前说清楚免得意外：

- 没有任何东西会自动把它改回来。唯一的恢复方式是 `restore`，或者用 `restore_file.py` 从备份恢复，都是人手动跑。
- 每天 05:30（吉隆坡时间）的完整性扫描会发现字节变了，记一条 `MODIFIED` 检查并把文件状态改成 `CORRUPTED`。从那以后 Bob 打开列表时这一行已经显示 **Modified**。
  这对演示没影响：现场要看的是下载被拒，标签反正都是 Modified。
- 安全代理 06:00 跑一次，因为有 Critical 的发现，会给团队的告警邮箱发邮件。答辩当天早上会收到这封邮件，不用理。这也正是第 5 步能看到的东西：Admin 页显示的就是同一条 `INTEGRITY_DAMAGE`。
- 上台前不要用 `demo-alice` 点这个文件的状态标签或者下载它。点了也不影响结果，但第一次被拒最好留给观众看。

讲完之后粘贴 `restore` 命令，再用 `demo-alice` 点一下这个文件的 **Modified** 标签。它会先显示 “Checking…” 几秒钟，服务器重新算完哈希后变回
Verified，代理下一次报告里这条发现就消失了。

## 前一天

- [ ] 两个演示账号都能登录 staging，`quarterly-results.txt` 已从 Alice 分享给 Bob，Bob 打开过一次。
- [ ] 已对 `quarterly-results.txt` 执行 `demo_tamper.py flip`，`list` 显示它标着 TAMPERED；`restore` 命令已填好文件 id，讲完用。
- [ ] 窗口 A 能打开 Education 和 AES-256-GCM 卡片，`board-minutes.pdf` 的 Details 抽屉里能看到 Alice 的 **Access history**。
- [ ] 管理员窗口能打开 Admin → Security agent；文件被拒过一次（或者 05:30 的扫描跑过）之后，这个页面显示 Critical 的 `INTEGRITY_DAMAGE`。
- [ ] 完整计时预演一次。预演被拒下载可以另外准备一个一次性文件；或者接受预演已经把这一行变成 Modified，每次下载都会再被拒一次，现场照样成立。
- [ ] staging 的恢复公钥是 **ACTIVE**：管理员在 Admin → Recovery key 能看到；或者直接开始预演上传，不是 ACTIVE 会立刻报
      “The recovery key is not active”。每次上传都要把文件密钥包装到这把公钥上，没有它什么都传不了。
- [ ] `board-minutes.pdf` 最多几 MB。浏览器会把整个文件读进内存，加密，再解密一遍自检，然后才上传，大文件在台上只会慢，没有任何好处；
      500 MiB 的上限留给幻灯片讲，不要在现场试。
- [ ] 备用视频已经录好（见下文），并拷到演示用的电脑上。
- [ ] 如果不用 staging 而是本机构建演示，先在 `frontend/` 下跑 `npm ci`。2026-10-05 之前装的 `node_modules` 没有自托管字体包，构建会失败。
- [ ] 展示前两小时内不要往 `main` 合并任何东西。合并会触发自动部署，服务会重启几秒钟。

## 答辩当天早上

- [ ] 用答辩电脑在 staging 上注册一个临时账号 `demo-carol-<日期>`。一分钟内收到邮件验证码，就在演示时段开头现场展示 AC1；收不到就留在幻灯片上讲
      （[RTM_DEMO_MAP.zh-CN.md](RTM_DEMO_MAP.zh-CN.md) 的“当天的 AC1”）。
- [ ] 06:00 安全代理关于 `quarterly-results.txt` 的告警邮件已经收到。这是预期的，说明 flip 还在。

## 开始前 30 分钟

- [ ] 健康检查：`https://secureview.tech/health/live` 返回 200。
- [ ] 两个窗口都已登录，两个口令都准备好。每次 Download and decrypt 和每次分享都会要求输入口令（第 2 步 Alice 一次，第 3、4 步 Bob 各一次），
      用完密钥马上重新锁上，所以不需要提前解锁。
- [ ] 浏览器缩放 125%；关掉通知和聊天软件；关掉密码管理器的弹窗。
- [ ] `board-minutes.pdf` 放在桌面上；如果 Alice 的 My Files 里有之前上传的同名文件，先删掉。
- [ ] 窗口 C 已用管理员登录并停在 Admin → Security agent，第 5 步只需要一次点击。
- [ ] 准备好手机热点，以防会场网络出问题。

## 出问题时

| 问题 | 处理 |
| --- | --- |
| 断网，或者 staging 没有响应 | 切到备用视频的同一步；视频和本脚本步骤一致 |
| 解锁或下载卡住超过约 10 秒 | 说一句“这里本来会……”，切到视频的这一步 |
| 下载或分享时弹出口令框 | 每次都会弹，输入口令继续 |
| Bob 的列表没显示新分享或 Modified 那行 | 点列表的刷新按钮，或者再点一下窗口；窗口回到前台时会自动重新加载 |
| 篡改后下载居然成功了 | `flip` 没有生效（有人跑了 `restore`，或者 `list` 里没有 TAMPERED 标记）；播放视频的第 4 步并展示 Modified 的截图 |
| Security agent 页没有 Critical 发现 | 文件在 flip 之后还没被检查过；第 4 步下载被拒之后就会出现，点页面的 Refresh。还没有就展示截图 |
| 点错了 | 不要现场补救，直接进入下一步 |

## 备用视频

已录好：[`media/demo-backup.mp4`](media/demo-backup.mp4)（2 分 23 秒，无声音，1280×720）。它按本脚本逐步
进行，并标明当前是谁的屏幕（Alice 或 Bob 的浏览器）；第 4 步真的改动了存储的文件：视频里的卡片显示的就是实际执行的
`demo_tamper.py flip` 命令和它的输出，录完后文件已还原。把它拷到演示电脑上，确认断网也能播放。演讲者边放边讲时可以随时
暂停；它故意比 4 分钟的时段短。

它是在一个本地的一次性环境上录的，运行的代码和 staging 相同（录制脚本会自动登录，这只在本地环境上做）。它录于 2026-10-05，
早于 PR #215，所以上传页面有点旧：算法下拉框没有等级和说明框，上传完成后显示的是可以点的“Encryption Complete”按钮，
而不是绿色的状态提示。其余流程和现在的 staging 一样。
界面改动后要重录，在 `frontend/` 下、本地环境跑着并有两个本地 `demo-*` 账号时执行：

```bash
node scripts/record-demo.mjs --base http://localhost:5173 --accounts accounts.json --tamper tamper.sh --out ../docs/presentation/media
```

`tamper.sh` 负责加载本地环境变量后执行 `backend/scripts/demo_tamper.py "$@"`。
