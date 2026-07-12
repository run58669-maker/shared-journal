# -*- coding: utf-8 -*-
"""共享手账 MCP server —— 让 Claude Code / Claude Desktop / Claude.ai 直接读写手账。

依赖: pip install "mcp[cli]"

两种运行方式（环境变量 JOURNAL_MCP_TRANSPORT）：
  - stdio (默认)：Claude Code / Claude Desktop 本地接入
  - http：streamable-http，给 Claude.ai 官网/手机 App 的自定义连接器用
          （需要公网可达：Tailscale Funnel / Cloudflare Tunnel 均可）

与 HTTP 前端并发安全：保存走 _rev 自增，前端旧缓存无法覆盖 MCP 新写的页。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

import journal_history
import journal_toc

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
JOURNAL_PATH = Path(os.environ.get("JOURNAL_DATA") or (ROOT / "data" / "journal_data.json"))

mcp = FastMCP("shared-journal")


def _load() -> dict:
    try:
        return json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"pages": [], "cur": 0, "tpl": "lined", "theme": "classic",
                "author": "q", "stickerLib": [], "_ts": 0}


def _save(data: dict, source: str = "mcp"):
    import time
    journal_toc.rebuild(data)
    data["_ts"] = int(time.time() * 1000)
    data["_rev"] = int(data.get("_rev", 0)) + 1
    new_raw = json.dumps(data, ensure_ascii=False)
    old_raw = JOURNAL_PATH.read_text(encoding="utf-8") if JOURNAL_PATH.exists() else ""
    journal_history.record(old_raw, new_raw, source)
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.write_text(new_raw, encoding="utf-8")


@mcp.tool()
def journal_read(page: int = -1) -> str:
    """读取手账内容。page=-1 返回所有页概要；page=0,1,2... 返回该页全文和元素。"""
    d = _load()
    if not d["pages"]:
        return "手账是空的，还没有任何页。"
    if page == -1:
        lines = [f"共 {len(d['pages'])} 页 | 主题: {d.get('theme','classic')}"]
        for i, p in enumerate(d["pages"]):
            txt = (p.get("flowText") or "")[:80].replace("\n", " ")
            lines.append(f"  第{i+1}页: {txt} [{len(p.get('elements', []))}贴纸"
                         f" {len(p.get('highlights', []))}高亮]")
        return "\n".join(lines)
    if page < 0 or page >= len(d["pages"]):
        return f"ERROR: 页码 {page} 不存在（共 {len(d['pages'])} 页，从0开始）"
    p = d["pages"][page]
    parts = [f"=== 第{page+1}页 ===", f"文字:\n{p.get('flowText','')}"]
    for h in p.get("highlights", []):
        parts.append(f"  高亮: \"{h.get('text','')}\"")
    for e in p.get("elements", []):
        parts.append(f"  贴纸: {e.get('name','?')} @ ({e.get('x',0)},{e.get('y',0)})")
    return "\n".join(parts)


@mcp.tool()
def journal_write(text: str, page: int = -1, signature: str = "",
                  append: bool = True, title: str = "") -> str:
    """写手账。page=-1 新建一页；signature 是署名（如你的名字/模型名），自动附日期。"""
    d = _load()
    sig = f"\n\n—— {signature} · {datetime.now().strftime('%Y.%m.%d')}" if signature else ""
    full_text = text + sig
    if page == -1:
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        d["pages"].append({
            "canvasData": None, "elements": [], "flowText": full_text,
            "flowFx": "wrap", "highlights": [],
            "entryTitle": (title or first_line[:20]),
        })
        idx = len(d["pages"]) - 1
    else:
        if page < 0 or page >= len(d["pages"]):
            return f"ERROR: 页码 {page} 不存在（共 {len(d['pages'])} 页）"
        if append:
            old = d["pages"][page].get("flowText", "")
            d["pages"][page]["flowText"] = old + "\n\n" + full_text if old else full_text
        else:
            d["pages"][page]["flowText"] = full_text
        if title:
            d["pages"][page]["entryTitle"] = title
        idx = page
    _save(d)
    return f"OK: 写入第{idx+1}页（共{len(d['pages'])}页）"


@mcp.tool()
def journal_highlight(text: str, color: str = "pink", page: int = 0) -> str:
    """给页面文字加荧光笔。color: pink/yellow/blue/green 或 rgba(...)。text 必须与页面原文完全一致。"""
    color_map = {
        "pink": "rgba(244,143,177,.40)",
        "yellow": "rgba(255,241,118,.50)",
        "blue": "rgba(144,202,249,.45)",
        "green": "rgba(165,214,167,.45)",
    }
    d = _load()
    if page < 0 or page >= len(d["pages"]):
        return f"ERROR: 页码 {page} 不存在（共 {len(d['pages'])} 页）"
    flow = d["pages"][page].get("flowText", "")
    if text not in flow:
        return f"ERROR: 第{page+1}页找不到「{text}」"
    d["pages"][page].setdefault("highlights", []).append(
        {"text": text, "color": color_map.get(color, color)})
    _save(d)
    return f"OK: 第{page+1}页「{text[:20]}」已标注 {color}"


@mcp.tool()
def journal_add_sticker(sticker_name: str, page: int = 0, x: int = 100,
                        y: int = 100, w: int = 120, h: int = 120) -> str:
    """在页面上放贴纸（贴纸须已在贴纸库里，用 journal_sticker_lib 查看）。"""
    d = _load()
    if page < 0 or page >= len(d["pages"]):
        return f"ERROR: 页码 {page} 不存在（共 {len(d['pages'])} 页）"
    lib = d.get("stickerLib", [])
    if not any(s.get("name") == sticker_name for s in lib):
        names = [s.get("name", "") for s in lib]
        return f"ERROR: 贴纸库没有「{sticker_name}」。可用: {', '.join(names) or '(空)'}"
    d["pages"][page].setdefault("elements", []).append({
        "type": "sticker", "name": sticker_name,
        "x": x, "y": y, "w": w, "h": h, "locked": True,
    })
    _save(d)
    return f"OK: 贴纸「{sticker_name}」放在第{page+1}页 ({x},{y})"


@mcp.tool()
def journal_sticker_lib() -> str:
    """列出贴纸库所有贴纸名。"""
    lib = _load().get("stickerLib", [])
    if not lib:
        return "贴纸库是空的（在网页端上传贴纸后即可用）。"
    return f"共 {len(lib)} 张:\n" + "\n".join(f"  - {s['name']}" for s in lib)


if __name__ == "__main__":
    transport = os.environ.get("JOURNAL_MCP_TRANSPORT", "stdio")
    if transport == "http":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("JOURNAL_MCP_PORT", "8790"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
