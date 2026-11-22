# -*- coding: utf-8 -*-
"""把「依赖题现在的装配输出」摊开看：卡片里到底有什么、漏了什么。

对几种典型符号各装配一道依赖题：
  A 仓库内被调用名很多（>6）
  B 只调用了对象方法（self.x() / obj.y()）
  C 只调用内置/外部函数（仓库内为空）
  D 普通小函数（1~3 个）
并把我用 AST 数出来的"真实调用名"与卡片上的 calls 列表逐项对照。
"""
from __future__ import annotations

import ast as pyast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from ctxfold.assembler import assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
import m3_online as m3  # noqa: E402

STDLIB = Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")


def ast_calls(text: str) -> list[str]:
    """我自己的口径：所有 Call 的叶子名（含 obj.method() 取 method）。"""
    out: list[str] = []
    try:
        tree = pyast.parse(text)
    except SyntaxError:
        return out
    for node in pyast.walk(tree):
        if isinstance(node, pyast.Call):
            f = node.func
            name = f.id if isinstance(f, pyast.Name) else (f.attr if isinstance(f, pyast.Attribute) else "")
            if name and name not in out:
                out.append(name)
    return out


def pick(chunks, by, pred):
    for c in chunks:
        if c.tokens >= 40 and pred(c):
            return c
    return None


def main() -> int:
    chunks, index, sha = load_corpus(STDLIB / "http")
    by = {c.cid: c for c in chunks}
    repo_names = set(index)

    cases = []
    many = pick(chunks, by, lambda c: len([d for d in getattr(c, "deps", []) or [] if d in by]) > 6)
    if many:
        cases.append(("A 仓库调用多（>6）", many))
    meth = pick(chunks, by, lambda c: (not [d for d in getattr(c, "deps", []) or [] if d in by])
               and any(n.endswith((".", )) is False and n in c.text for n in [])
               and any(isinstance(x.func, pyast.Attribute) for x in _calls(c.text)))
    if meth:
        cases.append(("B 只调对象方法", meth))
    none_ = pick(chunks, by, lambda c: not [d for d in getattr(c, "deps", []) or [] if d in by])
    if none_:
        cases.append(("C 仓库内为空", none_))
    few = pick(chunks, by, lambda c: 1 <= len([d for d in getattr(c, "deps", []) or [] if d in by]) <= 3)
    if few:
        cases.append(("D 普通小函数", few))

    for label, ck in cases:
        deps = [by[d].name for d in getattr(ck, "deps", []) or [] if d in by]
        print("=" * 78)
        print(f"{label}  {ck.cid}   tokens={ck.tokens}")
        print(f"  代码里的调用（AST 口径）: {ast_calls(ck.text)}")
        print(f"  chunk.deps（仓库内解析）: {deps or '（空）'}")
        print(f"  chunk.call_order        : {list(ck.call_order or [])}")
        memory, hist = {}, []
        q = f"符号 {ck.name} 直接调用了哪些函数？只列函数名，用英文逗号分隔；没有就回答 none。"
        r1 = assemble("ours", q, hist, by, index, memory, sha, budget=1600)
        hist.append(r1.history_append)
        r2 = assemble("ours", q, hist, by, index, memory, sha, budget=1600)
        print("  --- 第 1 轮（原文）---")
        for ln in r1.prompt.splitlines():
            if ln.startswith(("### ", "- #", "[问题]", "[答题提示]")):
                print("   ", ln[:160])
        print("  --- 第 2 轮（已固化 -> 卡片/占位符）---")
        for ln in r2.prompt.splitlines():
            if ln.startswith(("### ", "- #", "[问题]", "[答题提示]")):
                print("   ", ln[:160])
        print(f"  层级: raw={r2.included_cids} card={r2.card_cids} ph={r2.placeholder_cids}")
    return 0


def _calls(text: str):
    try:
        return [n for n in pyast.walk(pyast.parse(text)) if isinstance(n, pyast.Call)]
    except SyntaxError:
        return []


if __name__ == "__main__":
    raise SystemExit(main())
