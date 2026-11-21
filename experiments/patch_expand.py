# -*- coding: utf-8 -*-
"""扩展实验（修正版）：新增两个强基线 + 多语料/多轮次扩展 + far_ref 空集保护。"""
import pathlib

ROOT = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold")
Q3 = chr(34) * 3   # 三个双引号
S3 = chr(39) * 3   # 三个单引号

# ---------- 1) m2_baselines ----------
P = ROOT / "experiments" / "m2_baselines.py"
s = P.read_text(encoding="utf-8")

helper = [
    "",
    "",
    "def compress_text(text: str) -> str:",
    '    """LLMLingua 的无模型近似：删注释、空行与 docstring，只保留可执行骨架。',
    "",
    "    真实 LLMLingua 用小模型逐 token 算信息熵做删减；此处退化为抽取式压缩，",
    '    压缩率固定在 40%~60%，在论文中标注为"无模型近似"。',
    '    """',
    "    out = []",
    "    for line in text.splitlines():",
    "        st = line.strip()",
    "        if not st or st.startswith('#') or st.startswith(" + repr(Q3) + ") or st.startswith(" + repr(S3) + "):",
    "            continue",
    "        out.append(line)",
    '    return chr(10).join(out)',
    "",
]
anchor = "\ndef run(method, tasks, by_cid, index, sha, bm25, budget, window=5, k=8):"
assert anchor in s
s = s.replace(anchor, "\n".join(helper) + anchor, 1)

new_branch = [
    '        elif method == "compress":',
    '            body = chr(10).join([h["text"] for h in history] + [compress_text(own.text)])',
    '            prompt = f"{body}" + chr(10) + chr(10) + f"[问题] {task[\'query\']}"',
    '            raw = {task["cid"]}',
    '            append, append_raw = compress_text(own.text), set()',
    '        elif method == "memgpt":',
    '            tail = history[-window:]',
    '            got = [c for c in bm25.top_k(task["query"], k=1, budget=budget) if c.cid != task["cid"]]',
    '            body = chr(10).join([h["text"] for h in tail] + [own.text]',
    '                                + [f"[归档检索] {c.text}" for c in got])',
    '            prompt = f"{body}" + chr(10) + chr(10) + f"[问题] {task[\'query\']}"',
    '            raw = {task["cid"]} | {c.cid for c in got}',
    '            append, append_raw = own.text, {task["cid"]}',
    '            raw = raw | (set().union(*[h["raw"] for h in tail]) if tail else set())',
    '        elif method == "grepriag":',
]
old_branch = '        elif method == "grepriag":'
assert old_branch in s
s = s.replace(old_branch, "\n".join(new_branch), 1)

s = s.replace('methods = ["full", "window", "summary", "grepriag", "ours"]',
              'methods = ["full", "window", "summary", "grepriag", "compress", "memgpt", "ours"]', 1)
s = s.replace('''        elif method == "summary":
            avail_raw = raw''',
              '''        elif method in ("summary", "compress"):
            avail_raw = raw''', 1)

# far_ref 为空时不要抛异常
s = s.replace('"r_prompt_far": round(st.mean(r["r_prompt"] for r in rows if r["far_ref"]), 4),',
              '"r_prompt_far": round(st.mean([r["r_prompt"] for r in rows if r["far_ref"]]), 4) if any(r["far_ref"] for r in rows) else 0.0,', 1)
P.write_text(s, encoding="utf-8")
print("m2 ok")

# ---------- 2) m9 ----------
P9 = ROOT / "experiments" / "m9_multicorpus.py"
s = P9.read_text(encoding="utf-8")
s = s.replace('''    ("stdlib/asyncio", STDLIB / "asyncio"),
    ("this-repo", ROOT / "src"),''',
              '''    ("stdlib/asyncio", STDLIB / "asyncio"),
    ("stdlib/collections", STDLIB / "collections"),
    ("stdlib/typing", STDLIB / "typing"),
    ("stdlib/logging", STDLIB / "logging"),
    ("stdlib/urllib", STDLIB / "urllib"),
    ("this-repo", ROOT / "src"),''', 1)
s = s.replace('ap.add_argument("--turns", type=int, default=60)',
              'ap.add_argument("--turns", type=int, default=100)', 1)
s = s.replace('ap.add_argument("--seeds", default="7,11,13,17,19,23,29,31,37,41")',
              'ap.add_argument("--seeds", default="7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83")', 1)
s = s.replace('for method in ("full", "window", "summary", "grepriag", "ours"):',
              'for method in ("full", "window", "summary", "grepriag", "compress", "memgpt", "ours"):')
P9.write_text(s, encoding="utf-8")
print("m9 ok")

import ast
for f in (P, P9):
    ast.parse(f.read_text(encoding="utf-8"))
print("syntax ok")
