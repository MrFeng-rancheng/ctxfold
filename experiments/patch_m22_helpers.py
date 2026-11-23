# -*- coding: utf-8 -*-
"""把 ours 的辅助函数补回去（扩任务库时被切掉了）。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m22_coding.py")
s = P.read_text(encoding="utf-8")

if "def ours_state(" in s:
    print("already present")
    raise SystemExit(0)

HELPERS = '''_STATE_CACHE: dict = {}


def ours_state(repo: Path):
    key = str(repo)
    if key not in _STATE_CACHE:
        from ctxfold.state import StateRuntime
        _STATE_CACHE[key] = StateRuntime(repo / "ctxfold", repo / ".ctxstate")
    return _STATE_CACHE[key]


def recall_file_text(st, task: dict, fail_out: str = "") -> str:
    """按报错里出现的符号名精确 recall，外加该文件的模块头。"""
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
    return "\\n\\n".join(blocks)


'''
anchor = "def build_repo("
assert anchor in s
s = s.replace(anchor, HELPERS + anchor, 1)
P.write_text(s, encoding="utf-8")
ast.parse(s)
print("helpers restored")
