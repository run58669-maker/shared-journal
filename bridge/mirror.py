# -*- coding: utf-8 -*-
"""脱敏镜像导出：手账 → Markdown（index.md + pages/page-NNN.md）。
只读 flowText / entryTitle / highlights / 贴纸名——canvasData(base64 画布)
永不读取。导出前逐条 redact，导出后再整体扫一遍残留，脏页拒绝落盘。
"""
import re
from pathlib import Path

from . import journal_ops

RE_DATAURL = re.compile(r"data:[a-zA-Z0-9.+/-]+;base64,[A-Za-z0-9+/=]+")
RE_LOCALPATH = re.compile(r"[A-Za-z]:\\[^\s\"'`<>|]*")
RE_B64BLOB = re.compile(r"[A-Za-z0-9+/=]{200,}")  # 疑似裸 base64 长块

# 导出内容里绝不该出现的东西（check_clean 用）
FORBIDDEN_MARKERS = ["data:image", ";base64,", "C:\\Users", "api_key",
                     "Authorization:", "ghp_", "github_pat_"]


def sanitize(text: str) -> str:
    text = RE_DATAURL.sub("[图片数据已略]", text or "")
    text = RE_LOCALPATH.sub("[本机路径已略]", text)
    text = RE_B64BLOB.sub("[二进制数据已略]", text)
    return text


def check_clean(text: str) -> list:
    return [m for m in FORBIDDEN_MARKERS if m.lower() in (text or "").lower()]


def export(out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "pages").mkdir(parents=True, exist_ok=True)
    toc = journal_ops.list_pages()
    rev = toc["revision"]

    index = ["# 手账 · 目录", "",
             f"- revision: {rev}", f"- 共 {toc['page_count']} 页", ""]
    violations = []
    for meta in toc["pages"]:
        i = meta["page"]
        title = sanitize(meta["title"]) or sanitize(meta["preview"])[:20] or "(无标题)"
        index.append(f"- 第{i+1}页 [{title}](pages/page-{i+1:03d}.md)"
                     f" — {meta['stickers']}贴纸 {meta['highlights']}高亮"
                     f"{' · 目录页' if meta['is_toc'] else ''}")
        p = journal_ops.read_page(i)
        body = [f"# 第{i+1}页 · {title}", "", f"- revision: {rev}", ""]
        body.append(sanitize(p["text"]))
        if p["highlights"]:
            body += ["", "## 高亮"]
            body += [f"- 「{sanitize(h['text'])}」 ({h['color']})" for h in p["highlights"]]
        if p["stickers"]:
            body += ["", "## 贴纸"]
            body += [f"- {sanitize(s['name'])}" for s in p["stickers"]]
        page_md = "\n".join(body) + "\n"
        bad = check_clean(page_md)
        if bad:
            violations.append({"page": i, "markers": bad})
            continue  # 有残留的页不落盘
        (out_dir / "pages" / f"page-{i+1:03d}.md").write_text(page_md, encoding="utf-8")

    index_md = "\n".join(index) + "\n"
    bad = check_clean(index_md)
    if bad:
        violations.append({"page": "index", "markers": bad})
    else:
        (out_dir / "index.md").write_text(index_md, encoding="utf-8")
    return {"revision": rev, "pages_exported": toc["page_count"] - len(violations),
            "violations": violations}
