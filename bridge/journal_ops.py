# -*- coding: utf-8 -*-
"""手账操作。保存语义与 server.py / mcp_server.py 完全一致：
toc rebuild → _ts → _rev+1 → history 追加 → 落盘。
写动作只允许 append/highlight/add_sticker——没有删页、没有整本替换。
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import journal_history  # noqa: E402
import journal_toc  # noqa: E402

from . import config  # noqa: E402


class RevConflict(Exception):
    def __init__(self, current_rev: int):
        self.current_rev = current_rev
        super().__init__(f"revision conflict, current rev = {current_rev}")


COLOR_MAP = {
    "pink": "rgba(244,143,177,.40)",
    "yellow": "rgba(255,241,118,.50)",
    "blue": "rgba(144,202,249,.45)",
    "green": "rgba(165,214,167,.45)",
}


def load() -> dict:
    try:
        return json.loads(config.JOURNAL_DATA.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"pages": [], "cur": 0, "tpl": "lined", "theme": "classic",
                "author": "q", "stickerLib": [], "_ts": 0}


def save(data: dict, actor: str):
    journal_toc.rebuild(data)
    data["_ts"] = int(time.time() * 1000)
    data["_rev"] = int(data.get("_rev", 0)) + 1
    new_raw = json.dumps(data, ensure_ascii=False)
    journal_history.HIST = config.JOURNAL_HISTORY
    old_raw = (config.JOURNAL_DATA.read_text(encoding="utf-8")
               if config.JOURNAL_DATA.exists() else "")
    journal_history.record(old_raw, new_raw, actor)
    config.JOURNAL_DATA.parent.mkdir(parents=True, exist_ok=True)
    config.JOURNAL_DATA.write_text(new_raw, encoding="utf-8")
    return data["_rev"]


def _check_rev(data: dict, expected_revision):
    current = int(data.get("_rev", 0))
    if expected_revision is not None and int(expected_revision) != current:
        raise RevConflict(current)


def list_pages() -> dict:
    d = load()
    pages = []
    for i, p in enumerate(d.get("pages", [])):
        txt = (p.get("flowText") or "")[:60].replace("\n", " ")
        pages.append({
            "page": i,
            "title": p.get("entryTitle", ""),
            "preview": txt,
            "stickers": len(p.get("elements", [])),
            "highlights": len(p.get("highlights", [])),
            "is_toc": bool(p.get("toc")),
        })
    return {"revision": int(d.get("_rev", 0)), "page_count": len(pages), "pages": pages}


def read_page(page: int) -> dict:
    d = load()
    pages = d.get("pages", [])
    if page < 0 or page >= len(pages):
        raise ValueError(f"页码 {page} 不存在（共 {len(pages)} 页，从0开始）")
    p = pages[page]
    return {
        "revision": int(d.get("_rev", 0)),
        "page": page,
        "title": p.get("entryTitle", ""),
        "text": p.get("flowText", ""),
        "highlights": [{"text": h.get("text", ""), "color": h.get("color", "")}
                       for h in p.get("highlights", [])],
        "stickers": [{"name": e.get("name", ""), "x": e.get("x"), "y": e.get("y")}
                     for e in p.get("elements", []) if e.get("type") == "sticker"],
    }


def append_page(text: str, title: str, model_label: str, actor: str,
                expected_revision=None) -> dict:
    d = load()
    _check_rev(d, expected_revision)
    sig = f"\n\n—— {model_label} · {datetime.now().strftime('%Y.%m.%d')}"
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    d["pages"].append({
        "canvasData": None, "elements": [], "flowText": text + sig,
        "flowFx": "wrap", "highlights": [],
        "entryTitle": (title or first_line[:20]),
    })
    idx = len(d["pages"]) - 1
    rev = save(d, actor)
    return {"page": idx, "page_count": len(d["pages"]), "new_revision": rev,
            "signed_as": model_label}


def highlight(page: int, text: str, color: str, actor: str,
              expected_revision=None) -> dict:
    d = load()
    _check_rev(d, expected_revision)
    pages = d.get("pages", [])
    if page < 0 or page >= len(pages):
        raise ValueError(f"页码 {page} 不存在（共 {len(pages)} 页）")
    flow = pages[page].get("flowText", "")
    if text not in flow:
        raise ValueError(f"第{page+1}页文字里找不到「{text}」，无法标注")
    pages[page].setdefault("highlights", []).append(
        {"text": text, "color": COLOR_MAP.get(color, color)})
    rev = save(d, actor)
    return {"page": page, "text": text, "color": color, "new_revision": rev}


def add_sticker(page: int, sticker_name: str, x: int, y: int, w: int, h: int,
                actor: str, expected_revision=None) -> dict:
    d = load()
    _check_rev(d, expected_revision)
    pages = d.get("pages", [])
    if page < 0 or page >= len(pages):
        raise ValueError(f"页码 {page} 不存在（共 {len(pages)} 页）")
    lib = d.get("stickerLib", [])
    if not any(s.get("name") == sticker_name for s in lib):
        names = [s.get("name", "") for s in lib]
        raise ValueError(f"贴纸库没有「{sticker_name}」。可用: {', '.join(names) or '(空)'}")
    pages[page].setdefault("elements", []).append({
        "type": "sticker", "name": sticker_name,
        "x": x, "y": y, "w": w, "h": h, "locked": True,
    })
    rev = save(d, actor)
    return {"page": page, "sticker": sticker_name, "new_revision": rev}
