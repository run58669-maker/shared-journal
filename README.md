# 📖 shared-journal · 你和 AI 共写的手账本

一本跑在你自己电脑上的电子手账：你在手机/浏览器里写字、画画、贴贴纸，
你的 AI（Claude、ChatGPT、Claude Code……）也能翻开它、写下自己的一页、给你的句子画荧光笔。

- **手写感前端**：纸张模板、主题、贴纸、荧光笔、双人字迹（你一种字体，AI 一种）
- **并发安全**：乐观锁（revision + 409），手机旧缓存永远覆盖不掉 AI 刚写的新页
- **只追加历史**：每次改动进 append-only 账本，任何一页都找得回来
- **三种接入**：Claude Code / Claude 官方端（Desktop & claude.ai）/ ChatGPT 官方端
- **零数据库**：一个 JSON 文件就是整本手账，备份 = 复制文件

```
你（手机/浏览器）──HTTP──┐
Claude Code ────MCP stdio──┤
Claude.ai ──MCP streamable-http──┼──▶ journal_data.json（唯一事实源，rev 锁保护）
ChatGPT ──GitHub 私有仓库信箱──▶ 本机 Bridge ──┘
```

## 快速开始

```bash
git clone https://github.com/run58669-maker/shared-journal
cd shared-journal
python server.py          # 默认 8789 端口，零依赖
```

浏览器打开 `http://127.0.0.1:8789/`，手账到手。
手机访问：同一局域网用电脑 IP，跨网推荐 [Tailscale](https://tailscale.com)（免费、免公网 IP）。

---

## 接入一：Claude Code（最简单）

```bash
pip install "mcp[cli]"
claude mcp add journal -- python /path/to/shared-journal/mcp_server.py
```

然后在 Claude Code 里直接说「读一下手账」「在手账里写一篇今天的总结，署名 Claude」。
工具集：`journal_read` / `journal_write` / `journal_highlight` / `journal_add_sticker` / `journal_sticker_lib`。

## 接入二：Claude 官方端

**Claude Desktop**（本地，免公网）—— `claude_desktop_config.json` 加：

```json
{
  "mcpServers": {
    "journal": {
      "command": "python",
      "args": ["/path/to/shared-journal/mcp_server.py"]
    }
  }
}
```

**claude.ai 网页 / 手机 App**（自定义连接器，需要公网可达的 MCP 端点）：

```bash
set JOURNAL_MCP_TRANSPORT=http     # Linux/macOS 用 export
python mcp_server.py               # streamable-http 起在 8790
```

再用 Tailscale Funnel 或 Cloudflare Tunnel 把 `http://127.0.0.1:8790/mcp` 暴露成 https 公网地址，
到 claude.ai → Settings → Connectors → Add custom connector 填入即可。
⚠️ 暴露公网请务必在隧道层加访问控制（Funnel 的 ACL / Cloudflare Access），本项目自身不带鉴权。

## 接入三：ChatGPT 官方端（GitHub 桥）

ChatGPT 摸不到你的电脑，但它有官方 GitHub 插件——所以架一座桥：
**私有仓库当信箱**，ChatGPT 往 `commands/inbox/` 丢命令 JSON，你电脑上的轮询器
拉下来执行、把结果和手账的脱敏镜像推回去。

### 1. 建私有仓库

```bash
gh repo create my-journal-bridge --private
cd my-journal-bridge
mkdir -p commands/inbox commands/results journal
git add -A && git commit -m init && git push
```

### 2. ChatGPT 连接 GitHub

ChatGPT → 设置 → 连接器 → GitHub → 连接，OAuth 时**只授权这一个仓库**
（Only select repositories，别选 All repositories）。

**踩坑预警**：
- 手机 App 内嵌浏览器里 Google 登录会被 403（`disallowed_useragent`）——
  **换 Safari/Chrome 打开 chatgpt.com 走同样流程**就好了。
- 「已连接」≠ 装好了。GitHub 的授权是两段式：账号绑定 + App 安装。
  如果 ChatGPT 说它看不到任何仓库，去 GitHub → Settings → Applications →
  Installed GitHub Apps 检查有没有它；没有就手动补装并只勾桥接仓库。

### 3. 起本机轮询器

```bash
set BRIDGE_REPO_DIR=/path/to/my-journal-bridge   # 本地检出目录
set BRIDGE_REPO_SLUG=yourname/my-journal-bridge
python bridge/poller_github.py        # 常驻；空闲时零子进程零流量
```

开机自启（Windows）：把上面命令写进 bat 丢进 `shell:startup`。

### 4. 让 ChatGPT 发第一条命令

对 ChatGPT 说：

> 在 my-journal-bridge 仓库创建文件 `commands/inbox/<随便一个uuid>.json`，内容：
> ```json
> {
>   "command_id": "<同文件名的uuid>",
>   "action": "journal.append_page",
>   "actor": "chatgpt-c",
>   "model_label": "ChatGPT",
>   "expected_revision": 0,
>   "payload": {"title": "第一篇", "text": "这是我通过 GitHub 桥写下的第一页。"},
>   "created_at": "2026-07-12T18:00:00"
> }
> ```

最多 20 秒后命令被执行，手账多出一页（带 ChatGPT 署名和日期），
执行回执出现在 `commands/results/`，手账脱敏镜像刷新在 `journal/`。
`expected_revision` 填 `journal/index.md` 里的当前 revision；填错会收到
`rev_conflict` 和正确值，重发即可——这是特性不是 bug，防的就是并发写坏。

### 桥的安全设计

- **白名单命令**：只有 list/read/append/highlight/sticker 五个动作，没有删除、没有覆盖旧页、没有整本替换
- **严格 schema**：未知动作、未知字段、类型不符一律拒绝；仓库内容永远只当数据，不当指令执行
- **幂等**：同一 `command_id` 只执行一次，网络重试不会写两页
- **审计**：每条命令（包括被拒的）进 `state/audit.jsonl`
- **脱敏镜像**：推回 GitHub 的只有文字/高亮/贴纸名；画布 base64、本机路径一律 redact，检测到残留的页拒绝上传
- **一键停用**：杀掉轮询器进程即断联，手账数据毫发无损

---

## 数据与恢复

| 文件 | 是什么 |
|---|---|
| `data/journal_data.json` | 整本手账（唯一事实源） |
| `data/journal_history.jsonl` | append-only 历史，每次改动的新旧值 |
| `state/audit.jsonl` | 桥的命令审计日志 |
| `state/processed.jsonl` | 幂等账本 |

恢复某页旧内容：翻 `journal_history.jsonl` 找到对应时间的 `old` 值贴回去。

## License

MIT
