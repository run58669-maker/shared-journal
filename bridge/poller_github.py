# -*- coding: utf-8 -*-
"""GitHub 同步轮询器：发现新提交 → pull → 处理 commands/inbox/*.json →
写 results/ + 移入 processed/ → 手账有变动就刷新 journal/ 镜像 → commit + push。

空闲周期零子进程（不闪窗口、不动磁盘）：用进程内 HTTPS 比对远端 head，
只有真有新提交才动 git。

用法: python bridge/poller_github.py [循环数, 0=常驻] [间隔秒, 默认20]
前提: 本机 git 已配好该仓库推拉权限；gh CLI 已登录（用于取 API token）。
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bridge import config, dispatcher, mirror  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = config.BRIDGE_REPO_DIR
INBOX = REPO / "commands" / "inbox"
RESULTS = REPO / "commands" / "results"
PROCESSED = REPO / "commands" / "processed"
LOG = config.STATE_DIR / "poller.log"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows 下不闪控制台

# 单实例守卫：端口被占 = 已有轮询器在跑，直接退出（防双开重复处理）
_guard = socket.socket()
try:
    _guard.bind(("127.0.0.1", config.SINGLETON_PORT))
except OSError:
    sys.exit(0)


def log(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def git(*args):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    return r.returncode, (r.stdout + r.stderr).strip()


_token = None
_local_head = None


def _gh_token() -> str:
    global _token
    if _token is None:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                           creationflags=NO_WINDOW)
        _token = r.stdout.strip()
    return _token


def _remote_head():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{config.BRIDGE_REPO_SLUG}/commits/HEAD",
        headers={"Authorization": f"Bearer {_gh_token()}",
                 "User-Agent": "shared-journal-poller",
                 "Accept": "application/vnd.github+json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        return json.loads(resp.read())["sha"]


def cycle() -> int:
    global _local_head
    if _local_head is None:
        _local_head = git("rev-parse", "HEAD")[1]
    try:
        if _remote_head() == _local_head:
            return 0
    except Exception as e:
        log(f"remote check failed: {e}")
        return 0
    code, out = git("pull", "--rebase", "--quiet")
    if code != 0:
        log(f"pull failed: {out[:300]}")
        return 0
    _local_head = git("rev-parse", "HEAD")[1]
    cmds = sorted(f for f in INBOX.glob("*.json"))
    if not cmds:
        return 0
    RESULTS.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    journal_changed = False
    for f in cmds:
        try:
            cmd = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            result = {"command_id": None, "status": "rejected",
                      "error": f"JSON 解析失败: {e}", "source_file": f.name}
        else:
            result = dispatcher.handle_command(cmd)
        if result.get("status") == "ok" and str(result.get("action", "")).startswith("journal."):
            journal_changed = True
        name = result.get("command_id") or f.stem
        (RESULTS / f"{name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        f.rename(PROCESSED / f.name)
        log(f"{f.name} -> {result.get('status')}")
    if journal_changed:
        mr = mirror.export(REPO / "journal")
        log(f"mirror refreshed rev={mr['revision']} violations={len(mr['violations'])}")
    git("add", "-A")
    git("commit", "-m", f"bridge: 处理 {len(cmds)} 条命令", "--quiet")
    code, out = git("push", "--quiet")
    if code != 0:
        log(f"push failed: {out[:300]}")
    _local_head = git("rev-parse", "HEAD")[1]
    return len(cmds)


if __name__ == "__main__":
    if not config.BRIDGE_REPO_SLUG:
        print("请先设置环境变量 BRIDGE_REPO_SLUG（例: yourname/my-journal-bridge）")
        sys.exit(1)
    loops = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    log(f"poller up: {'forever' if loops <= 0 else loops} cycles x {interval}s, repo={REPO}")
    i = 0
    while loops <= 0 or i < loops:
        i += 1
        try:
            cycle()
        except Exception as e:
            log(f"cycle error: {e}")
        time.sleep(interval)
    log("poller done")
