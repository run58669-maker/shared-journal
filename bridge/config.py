# -*- coding: utf-8 -*-
"""GitHub 桥配置——全部可用环境变量覆盖。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

JOURNAL_DATA = Path(os.environ.get("JOURNAL_DATA") or (ROOT / "data" / "journal_data.json"))
JOURNAL_HISTORY = Path(os.environ.get("JOURNAL_HISTORY")
                       or (ROOT / "data" / "journal_history.jsonl"))

# 命令仓库：本地 git 检出目录 + GitHub 上的 owner/name
BRIDGE_REPO_DIR = Path(os.environ.get("BRIDGE_REPO_DIR") or (ROOT / "bridge_repo"))
BRIDGE_REPO_SLUG = os.environ.get("BRIDGE_REPO_SLUG", "")  # 例: yourname/my-journal-bridge

STATE_DIR = Path(os.environ.get("BRIDGE_STATE_DIR") or (ROOT / "state"))
PROCESSED_LEDGER = STATE_DIR / "processed.jsonl"   # command_id → 结果（幂等）
AUDIT_LOG = STATE_DIR / "audit.jsonl"              # 每条进来的命令都留痕

# 允许的命令发起方；保留署名 = 别人不许冒用的签名（逗号分隔）
ALLOWED_ACTORS = set(filter(None, os.environ.get("BRIDGE_ACTORS", "chatgpt-c").split(",")))
RESERVED_SIGNATURES = set(filter(None, os.environ.get("BRIDGE_RESERVED_SIGS", "").split(",")))

SINGLETON_PORT = int(os.environ.get("BRIDGE_SINGLETON_PORT", "48765"))
