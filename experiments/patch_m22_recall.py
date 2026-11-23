# -*- coding: utf-8 -*-
"""给 m22 的 ours 分支补一条动作：先用 recall(cid) 取回目标文件原文，再让模型改。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m22_coding.py")
s = P.read_text(encoding="utf-8")

# 1) 每个任务缓存一个 StateRuntime（ours 用），并提供"按 id 取回目标文件原文"
helper = '''_STATE_CACHE: dict = {}


def ours_state(repo: Path):
    key = str(repo)
    if key not in _STATE_CACHE:
        from ctxfold.state import StateRuntime
        _STATE_CACHE[key] = StateRuntime(repo / "ctxfold", repo / ".ctxstate")
    return _STATE_CACHE[key]


def recall_file_text(st, task: dict) -> str:
    """按 id 取回目标文件里每个符号的原文（这正是 recall 接口的用法）。"""
    blocks = []
    for cid in st.rt.by_cid:
        if cid.split("::")[0].endswith(task["file"]):
            r = st.recall(cid)
            blocks.append(f"### #{cid} | {r['path']}:{r['start']}-{r['end']}\\n{r['text']}")
    return "\\n\\n".join(blocks)


'''
s = s.replace("def build_repo(", helper + "def build_repo(", 1)

# 2) ours 分支：装配后追加 recall 取回的原文
old_ours = '''    chunks, index, sha = load_corpus(repo / "ctxfold")
    by = {c.cid: c for c in chunks}
    res = assemble("ours", q, history, by, index, memory, sha, budget=BUDGET)
    return res.prompt, (by, index, sha, res)'''
new_ours = '''    st = ours_state(repo)
    out = st.assemble(q)
    prompt = out["prompt"] + "\\n\\n[按 id 取回的原文]\\n" + recall_file_text(st, task)
    return prompt, ("ours", st)'''
assert old_ours in s
s = s.replace(old_ours, new_ours, 1)

# 3) 失效统计改成用 StateRuntime.invalidate（装配前）
old_inv = '''        if method == "ours":
            chunks, index, sha = load_corpus(repo / "ctxfold")
            by = {c.cid: c for c in chunks}
            inv = [cid for cid, m in memory.items()
                   if cid in by and m.chunk_sha and m.chunk_sha != by[cid].text_sha]
            invalidations.append(len(inv))
            for cid in inv:
                memory[cid].status = "stale"'''
new_inv = '''        if method == "ours":
            st = ours_state(repo)
            info = st.invalidate()
            invalidations.append(len(info["invalidated"]) + len(info["downstream"]))'''
assert old_inv in s
s = s.replace(old_inv, new_inv, 1)

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("m22 patched: ours 每步先 recall 目标文件原文")
