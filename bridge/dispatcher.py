# -*- coding: utf-8 -*-
"""命令分发：校验 → 幂等检查 → 执行 → 结果 + 审计。
幂等账本 processed.jsonl：同一 command_id 只执行一次，重放直接返回上次结果。
rev_conflict / error 不进账本——没有产生副作用，允许修正后重试。
"""
import json
import time

from . import config, journal_ops, validate


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _load_ledger() -> dict:
    ledger = {}
    if config.PROCESSED_LEDGER.exists():
        for line in config.PROCESSED_LEDGER.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                ledger[rec["command_id"]] = rec["result"]
            except (json.JSONDecodeError, KeyError):
                continue
    return ledger


def _append(path, obj):
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _audit(cmd, verdict: str, detail: str = ""):
    _append(config.AUDIT_LOG, {
        "ts": _now_iso(),
        "command_id": cmd.get("command_id") if isinstance(cmd, dict) else None,
        "action": cmd.get("action") if isinstance(cmd, dict) else None,
        "actor": cmd.get("actor") if isinstance(cmd, dict) else None,
        "verdict": verdict,
        "detail": detail[:500],
    })


def _execute(cmd: dict) -> dict:
    action = cmd["action"]
    p = cmd["payload"]
    actor = f"bridge:{cmd['actor']}"
    exp = cmd.get("expected_revision")
    if action == "journal.list":
        return journal_ops.list_pages()
    if action == "journal.read":
        return journal_ops.read_page(p["page"])
    if action == "journal.append_page":
        return journal_ops.append_page(p["text"], p.get("title", ""),
                                       cmd["model_label"], actor, exp)
    if action == "journal.highlight":
        return journal_ops.highlight(p["page"], p["text"], p.get("color", "pink"),
                                     actor, exp)
    if action == "journal.add_sticker":
        return journal_ops.add_sticker(p["page"], p["sticker_name"],
                                       p.get("x", 100), p.get("y", 100),
                                       p.get("w", 120), p.get("h", 120),
                                       actor, exp)
    raise validate.Rejected(f"动作未实现: {action}")


def handle_command(cmd) -> dict:
    """入口。永远返回结果 dict，不抛异常。"""
    cid = cmd.get("command_id") if isinstance(cmd, dict) else None
    try:
        cmd = validate.validate(cmd)
    except validate.Rejected as e:
        result = {"command_id": cid, "status": "rejected", "error": str(e),
                  "ts": _now_iso()}
        _audit(cmd if isinstance(cmd, dict) else {}, "rejected", str(e))
        return result

    ledger = _load_ledger()
    if cmd["command_id"] in ledger:
        prev = dict(ledger[cmd["command_id"]])
        prev["replay"] = True
        _audit(cmd, "duplicate_replay")
        return prev

    try:
        data = _execute(cmd)
        result = {"command_id": cmd["command_id"], "action": cmd["action"],
                  "status": "ok", "data": data, "ts": _now_iso()}
        _audit(cmd, "ok")
    except journal_ops.RevConflict as e:
        result = {"command_id": cmd["command_id"], "action": cmd["action"],
                  "status": "rev_conflict", "current_revision": e.current_rev,
                  "error": f"手账已更新到 rev {e.current_rev}，请先 journal.list 取最新 revision 再重发",
                  "ts": _now_iso()}
        _audit(cmd, "rev_conflict", str(e))
    except Exception as e:
        result = {"command_id": cmd["command_id"], "action": cmd["action"],
                  "status": "error", "error": str(e), "ts": _now_iso()}
        _audit(cmd, "error", str(e))

    if result["status"] == "ok":
        _append(config.PROCESSED_LEDGER,
                {"command_id": cmd["command_id"], "result": result})
    return result
