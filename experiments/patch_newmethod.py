# -*- coding: utf-8 -*-
"""加第 8 个基线：shortsym（不看查询，按符号长度升序装填预算）。"""
import ast
import pathlib

ROOT = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments")

# ---------- m2_baselines.py ----------
P = ROOT / "m2_baselines.py"
s = P.read_text(encoding="utf-8")
LOG = []


def rep(old, new, tag):
    global s
    assert old in s, "MISS " + tag
    assert s.count(old) == 1, "AMBIG %s x%d" % (tag, s.count(old))
    s = s.replace(old, new, 1)
    LOG.append(tag)


rep('        elif method == "grepriag":\n            got = bm25.top_k(task["query"], k=k, budget=budget)',
    '        elif method == "shortsym":\n'
    '            # 朴素强基线：完全不看查询，把最短的符号先塞满预算，尽量让 prompt 装下更多符号\n'
    '            picked, used = [], 0\n'
    '            for c in sorted(by_cid.values(), key=lambda x: x.tokens):\n'
    '                if used + c.tokens > budget:\n'
    '                    continue\n'
    '                picked.append(c)\n'
    '                used += c.tokens\n'
    '                if used >= int(budget * 0.98):\n'
    '                    break\n'
    '            body = "\\n\\n".join(c.text for c in picked)\n'
    '            prompt = f"[符号池]\\n{body}\\n\\n[问题] {task[\'query\']}"\n'
    '            raw = {c.cid for c in picked}\n'
    '            append, append_raw = "", set()\n'
    '        elif method == "grepriag":\n            got = bm25.top_k(task["query"], k=k, budget=budget)', "m2-branch")
rep('    methods = ["full", "window", "summary", "grepriag", "compress", "memgpt", "ours"]',
    '    methods = ["full", "window", "summary", "grepriag", "shortsym", "compress", "memgpt", "ours"]',
    "m2-methods")
P.write_text(s, encoding="utf-8")
ast.parse(s)

# ---------- m9_multicorpus.py ----------
P2 = ROOT / "m9_multicorpus.py"
t = P2.read_text(encoding="utf-8")
old = '("full", "window", "summary", "grepriag", "compress", "memgpt", "ours")'
new = '("full", "window", "summary", "grepriag", "shortsym", "compress", "memgpt", "ours")'
n = t.count(old)
assert n == 2, "m9 method tuples: %d" % n
t = t.replace(old, new)
P2.write_text(t, encoding="utf-8")
ast.parse(t)
print("ok:", ", ".join(LOG), "| m9 tuples replaced:", n)
