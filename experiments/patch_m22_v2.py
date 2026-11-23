# -*- coding: utf-8 -*-
"""m22 三处修补：
  ① ours 改成「按报错里的符号名精确 recall」+ 该文件的模块头（不再整文件取回）
  ② 单个任务出错不再拖垮整轮（try/except 包住）
  ③ T6 的注入点按 world.py 实际代码修正
"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m22_coding.py")
s = P.read_text(encoding="utf-8")

# ① 精确 recall
old = '''def recall_file_text(st, task: dict) -> str:
    """按 id 取回目标文件里每个符号的原文（这正是 recall 接口的用法）。"""
    blocks = []
    for cid in st.rt.by_cid:
        if cid.split("::")[0].endswith(task["file"]):
            r = st.recall(cid)
            blocks.append(f"### #{cid} | {r['path']}:{r['start']}-{r['end']}\\n{r['text']}")
    return "\\n\\n".join(blocks)'''
new = '''def recall_file_text(st, task: dict, fail_out: str = "") -> str:
    """按报错里出现的符号名精确 recall（外加该文件的模块头），而不是整文件取回。"""
    import re as _re
    cids = [c for c in st.rt.by_cid if c.split("::")[0].endswith(task["file"])]
    head = [c for c in cids if c.endswith("::<module>")]
    names = set(_re.findall(r"[A-Za-z_][A-Za-z0-9_]*", fail_out or ""))
    picked = [c for c in cids if not c.endswith("::<module>")
              and c.split("::")[-1] in names][:3]
    blocks = []
    for cid in head + picked:
        r = st.recall(cid)
        blocks.append(f"### #{cid} | {r['path']}:{r['start']}-{r['end']}\\n{r['text']}")
    return "\\n\\n".join(blocks)'''
assert old in s
s = s.replace(old, new, 1)

s = s.replace('prompt = out["prompt"] + "\\n\\n[按 id 取回的原文]\\n" + recall_file_text(st, task)',
              'prompt = out["prompt"] + "\\n\\n[按 id 取回的原文]\\n" + recall_file_text(st, task, fail_out)')

# ③ T6 注入点
s = s.replace('''        "bug": ("    return hashlib.sha256(repr(parts).encode()).hexdigest()[:16]",
                "    return hashlib.sha256(b'fixed').hexdigest()[:16]"),''',
'''        "bug": ('    return h.hexdigest()[:16]', "    return 'fixed0000000000'"),''')

# ② 单任务容错
s = s.replace('''        for m in methods:
            r = run_task(m, task)''','''        for m in methods:
            try:
                r = run_task(m, task)
            except Exception as e:
                print(f"{task['name'][:22]} {m} [ERROR] {type(e).__name__}: {e}", flush=True)
                continue''')

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("m22 patched: 精确 recall / 容错 / T6 注入点")
