# -*- coding: utf-8 -*-
"""命令严格校验：白名单动作、未知字段拒绝、类型检查、署名保护。
仓库里的内容一律当不可信输入——只接受这里定义的结构，其余全拒。
"""
from . import config


class Rejected(Exception):
    pass


WRITE_ACTIONS = {"journal.append_page", "journal.highlight", "journal.add_sticker"}
ACTIONS = {
    "journal.list":        ({}, {}),
    "journal.read":        ({"page": int}, {}),
    "journal.append_page": ({"text": str}, {"title": str}),
    "journal.highlight":   ({"page": int, "text": str}, {"color": str}),
    "journal.add_sticker": ({"page": int, "sticker_name": str},
                            {"x": int, "y": int, "w": int, "h": int}),
}

TOP_REQUIRED = {"command_id": str, "action": str, "actor": str,
                "model_label": str, "payload": dict, "created_at": str}
TOP_OPTIONAL = {"expected_revision": int}


def validate(cmd) -> dict:
    """校验通过返回命令本身；不通过抛 Rejected（消息可读）。"""
    if not isinstance(cmd, dict):
        raise Rejected("命令必须是 JSON object")

    unknown = set(cmd) - set(TOP_REQUIRED) - set(TOP_OPTIONAL)
    if unknown:
        raise Rejected(f"未知顶层字段: {sorted(unknown)}")
    for field, typ in TOP_REQUIRED.items():
        if field not in cmd:
            raise Rejected(f"缺少必填字段: {field}")
        if not isinstance(cmd[field], typ):
            raise Rejected(f"字段 {field} 类型错误，应为 {typ.__name__}")
    if "expected_revision" in cmd and not isinstance(cmd["expected_revision"], int):
        raise Rejected("expected_revision 应为 int")

    if not cmd["command_id"].strip():
        raise Rejected("command_id 不能为空")

    action = cmd["action"]
    if action not in ACTIONS:
        raise Rejected(f"动作不在白名单: {action}")

    if cmd["actor"] not in config.ALLOWED_ACTORS:
        raise Rejected(f"actor 不被允许: {cmd['actor']}")

    label = cmd["model_label"].strip()
    if not label:
        raise Rejected("model_label 不能为空")
    for reserved in config.RESERVED_SIGNATURES:
        if reserved.lower() in label.lower():
            raise Rejected(f"署名「{label}」冒充保留署名「{reserved}」，拒绝")

    if action in WRITE_ACTIONS and "expected_revision" not in cmd:
        raise Rejected(f"写动作 {action} 必须携带 expected_revision")

    required, optional = ACTIONS[action]
    payload = cmd["payload"]
    unknown_p = set(payload) - set(required) - set(optional)
    if unknown_p:
        raise Rejected(f"payload 未知字段: {sorted(unknown_p)}")
    for field, typ in required.items():
        if field not in payload:
            raise Rejected(f"payload 缺少必填字段: {field}")
        if not isinstance(payload[field], typ) or isinstance(payload[field], bool):
            raise Rejected(f"payload.{field} 类型错误，应为 {typ.__name__}")
    for field, typ in optional.items():
        if field in payload and (not isinstance(payload[field], typ)
                                 or isinstance(payload[field], bool)):
            raise Rejected(f"payload.{field} 类型错误，应为 {typ.__name__}")

    return cmd
