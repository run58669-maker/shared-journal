# -*- coding: utf-8 -*-
"""手账只追加历史账本（append-only）。

任何写入方（HTTP 前端 / MCP / GitHub 桥）在覆盖 journal_data.json 之前调用
record(old_raw, new_raw, source)，把这次写入改变了什么逐条追加到
data/journal_history.jsonl。恢复 = 翻 jsonl 找对应时间的 old 值。
铁律：history 写失败绝不能阻塞正常保存（全部吞异常）。
"""
import json
import os
import time
from pathlib import Path

HIST = Path(os.environ.get("JOURNAL_HISTORY")
            or (Path(__file__).parent / "data" / "journal_history.jsonl"))


def record(old_raw, new_raw, source):
    """对比新旧 JSON 字符串，把差异追加进历史。永不抛异常。"""
    try:
        _record(old_raw, new_raw, source)
    except Exception:
        pass


def _record(old_raw, new_raw, source):
    try:
        old = json.loads(old_raw) if old_raw else {}
    except Exception:
        old = {}
    new = json.loads(new_raw)

    changes = []
    op = old.get("pages") or []
    np = new.get("pages") or []
    for i in range(max(len(op), len(np))):
        o = op[i] if i < len(op) else {}
        p = np[i] if i < len(np) else {}
        if (o.get("flowText") or "") != (p.get("flowText") or ""):
            changes.append({"what": "text", "page": i,
                            "old": o.get("flowText") or "", "new": p.get("flowText") or ""})
        if (o.get("elements") or []) != (p.get("elements") or []):
            changes.append({"what": "elements", "page": i,
                            "old": o.get("elements") or [], "new": p.get("elements") or []})
        if (o.get("highlights") or []) != (p.get("highlights") or []):
            changes.append({"what": "highlights", "page": i,
                            "old": o.get("highlights") or [], "new": p.get("highlights") or []})
    if len(op) != len(np):
        changes.append({"what": "page_count", "old": len(op), "new": len(np)})
    for k in ("theme", "tpl"):
        if old.get(k) != new.get(k):
            changes.append({"what": k, "old": old.get(k), "new": new.get(k)})
    ol = {s.get("name"): s for s in (old.get("stickerLib") or [])}
    nl = {s.get("name"): s for s in (new.get("stickerLib") or [])}
    for name, entry in nl.items():
        if name not in ol:
            changes.append({"what": "sticker_lib_add", "name": name, "entry": entry})
        elif ol[name] != entry:
            changes.append({"what": "sticker_lib_change", "name": name,
                            "old": ol[name], "new": entry})
    for name, entry in ol.items():
        if name not in nl:
            changes.append({"what": "sticker_lib_remove", "name": name, "entry": entry})

    if not changes:
        return
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source, "changes": changes}
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
