# -*- coding: utf-8 -*-
"""手账目录页自动重建。

约定：带 "toc": true 的页是目录页；带 "entryTitle" 的页是一篇的开头。
rebuild(d) 用所有 entryTitle 重新生成目录页文字（标题+页码），
每次保存前调用 → 新篇自动上目录、页码永远是活的。
没有目录页则什么都不做（删掉目录页 = 关闭此功能）。
"""

CIRC = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def rebuild(d):
    """重建目录页文字。有改动返回 True。"""
    pages = d.get("pages") or []
    toc_idx = next((i for i, p in enumerate(pages) if p.get("toc")), None)
    if toc_idx is None:
        return False
    lines = ["📖 目录", ""]
    n = 0
    for i, p in enumerate(pages):
        if i == toc_idx or not p.get("entryTitle"):
            continue
        mark = CIRC[n] if n < len(CIRC) else "%d." % (n + 1)
        lines.append("%s %s ……… 第%d页" % (mark, p["entryTitle"], i + 1))
        n += 1
    new_text = "\n\n".join([lines[0], "\n".join(lines[2:])]) if n else lines[0]
    if pages[toc_idx].get("flowText") == new_text:
        return False
    pages[toc_idx]["flowText"] = new_text
    return True
