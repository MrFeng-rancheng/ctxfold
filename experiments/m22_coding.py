# -*- coding: utf-8 -*-
"""M22：多步编码任务（读代码 -> 改代码 -> 跑测试 -> 再改）·三方法对照。

任务形态：在 ctxfold 仓库的真实模块里注入一个小 bug，并放一个会失败的 pytest；
模型必须给出字符串替换补丁把测试修绿。允许最多 3 步，每步把测试失败输出回灌。

方法：full（整份目标文件）/ grepriag（BM25 top-k 片段）/ ours（状态化装配 + 失效重读）
指标：通过与否、交互步数、累计 token、端到端耗时、每次改动后的失效/重读条数。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold import llm  # noqa: E402
from ctxfold.assembler import assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.retrieve import BM25  # noqa: E402
from ctxfold.tokenize import token_count  # noqa: E402

BUDGET, MAX_STEPS = 1600, 3
PY = sys.executable

TASKS = [
    {"name": "T1 改模块常量", "file": "tokenize.py",
     "bug": ("_CHARS_PER_TOKEN = 3.5", "_CHARS_PER_TOKEN = 2.0"),
     "test": "from ctxfold.tokenize import token_count\n\n\ndef test_empty():\n"
             "    assert token_count('') == 0\n\n\ndef test_nonempty():\n"
             "    assert token_count('abcdefg') == 2\n"},
    {"name": "T2 改函数返回值", "file": "tokenize.py",
     "bug": ("def char_count(text: str) -> int:\n    return len(text)",
             "def char_count(text: str) -> int:\n    return len(text) + 1"),
     "test": "from ctxfold.tokenize import char_count\n\n\ndef test_len():\n"
             "    assert char_count('abc') == 3\n"},
    {"name": "T3 改格式化字符串", "file": "assembler.py",
     "bug": ('        lines.append(f"- #{cid} ({m.name})")',
             '        lines.append(f"- {cid} ({m.name})")'),
     "test": "from ctxfold.assembler import _placeholders\n\n\nclass M:\n    name = 'f'\n\n\n"
             "def test_hash():\n    out = _placeholders({'x::f': M()}, ['x::f'])\n"
             "    assert '#x::f' in out\n"},
    {"name": "T5 改 AST 解析分支", "file": "chunker.py",
     "bug": ("            elif isinstance(fn, ast.Attribute):\n                n = fn.attr",
             "            elif isinstance(fn, ast.Attribute):\n                n = None"),
     "test": "import ast\nfrom ctxfold.chunker import _collect_calls\n\n\ndef test_attr():\n"
             "    node = ast.parse('x.append(1)')\n    assert _collect_calls(node) == ['append']\n"},
    {"name": "T6 改指纹实现", "file": "world.py",
     "bug": ('    return h.hexdigest()[:16]', "    return 'fixed0000000000'"),
     "test": "import pathlib, tempfile\nfrom ctxfold.world import cheap_fingerprint\n\n\n"
             "def test_change():\n    d = pathlib.Path(tempfile.mkdtemp())\n"
             "    f = d / 'a.py'\n    f.write_text('x=1\\n', encoding='utf-8')\n"
             "    a = cheap_fingerprint(d)\n    f.write_text('x=2\\n' * 5, encoding='utf-8')\n"
             "    assert cheap_fingerprint(d) != a\n"},
    {"name": "T7 未加载块标题", "file": "assembler.py",
     "bug": ('        lines = ["[未加载，按需 recall 取原文]"]', "        lines = []"),
     "test": "from ctxfold.assembler import _recallable\n\n\nclass C:\n    name = 'f'\n\n\n"
             "def test_head():\n    out = _recallable({'x::f': C()}, ['x::f'])\n"
             "    assert '未加载' in out\n"},
    {"name": "T8 结论块标题", "file": "assembler.py",
     "bug": ('        lines = ["[已验证结论：可直接采用，无需重读代码]"]', "        lines = []"),
     "test": "from ctxfold.assembler import _claims\n\n\nclass M:\n    claim = 'c'\n\n\n"
             "def test_head():\n    out = _claims({'x::f': M()}, ['x::f'])\n"
             "    assert '已验证结论' in out\n"},
    {"name": "T9 快照键唯一性", "file": "state.py",
     "bug": ('            return f"{safe}.{hashlib.sha1(cid.encode(\'utf-8\')).hexdigest()[:8]}"',
             '            return f"{safe}"'),
     "test": "import pathlib, tempfile\nfrom ctxfold.state import StateRuntime\n\n\n"
             "def test_key():\n    d = pathlib.Path(tempfile.mkdtemp())\n"
             "    (d / 'a.py').write_text('def f():\\n    return 1\\n', encoding='utf-8')\n"
             "    st = StateRuntime(d, d / 'st')\n"
             "    assert st._snap_key('a/b::f') != st._snap_key('a_b::f')\n"},
    {"name": "T10 内容指纹应随内容变", "file": "world.py",
     "bug": ("            h.update(hashlib.sha256(p.read_bytes()).digest())",
             '            h.update(b"")'),
     "test": "import pathlib, tempfile\nfrom ctxfold.world import content_fingerprint\n\n\n"
             "def test_change():\n    d = pathlib.Path(tempfile.mkdtemp())\n"
             "    f = d / 'a.py'\n    f.write_text('x=1\\n', encoding='utf-8')\n"
             "    a = content_fingerprint(d)\n    f.write_text('y=2\\n', encoding='utf-8')\n"
             "    assert content_fingerprint(d) != a\n"},
    {"name": "T11 遍历应跳过缓存目录", "file": "world.py",
     "bug": ('        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]',
             "        dirnames[:] = dirnames"),
     "test": "import pathlib, tempfile\nfrom ctxfold.world import _iter_py\n\n\n"
             "def test_skip():\n    d = pathlib.Path(tempfile.mkdtemp())\n"
             "    (d / 'a.py').write_text('x=1\\n', encoding='utf-8')\n"
             "    c = d / '__pycache__'\n    c.mkdir()\n"
             "    (c / 'b.py').write_text('y=1\\n', encoding='utf-8')\n"
             "    names = [p.name for p in _iter_py(d)]\n    assert 'b.py' not in names\n"},
    {"name": "T12 top_k 应遵守 k", "file": "retrieve.py",
     "bug": ("            if len(out) >= k:", "            if len(out) >= k + 1:"),
     "test": "import pathlib, tempfile\nfrom ctxfold.chunker import load_corpus\n"
             "from ctxfold.retrieve import BM25\n\n\ndef test_k():\n"
             "    d = pathlib.Path(tempfile.mkdtemp())\n"
             "    for i in range(4):\n        (d / f'm{i}.py').write_text('def f%d():\\n    return %d\\n' % (i, i), encoding='utf-8')\n"
             "    chunks, index, sha = load_corpus(d)\n    bm = BM25(chunks)\n"
             "    assert len(bm.top_k('f1', k=2)) <= 2\n"},
    {"name": "T13 调用顺序应保持源码序", "file": "chunker.py",
     "bug": ("                names.append(n)\n    return names",
             "                names.append(n)\n    return sorted(names)"),
     "test": "import ast\nfrom ctxfold.chunker import _collect_calls\n\n\ndef test_order():\n"
             "    node = ast.parse('b()\\na()')\n    assert _collect_calls(node) == ['b', 'a']\n"},
]


_STATE_CACHE: dict = {}


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
        blocks.append(f"### #{cid} | {r['path']}:{r['start']}-{r['end']}\n{r['text']}")
    return "\n\n".join(blocks)


def build_repo(task: dict) -> Path:
    dst = Path(tempfile.mkdtemp(prefix="m22-")) / "repo"
    shutil.copytree(ROOT / "src" / "ctxfold", dst / "ctxfold")
    (dst / "tests").mkdir()
    (dst / "tests" / "test_task.py").write_text(task["test"], encoding="utf-8")
    p = dst / "ctxfold" / task["file"]
    old, new = task["bug"]
    src = p.read_text(encoding="utf-8")
    new_src, applied = apply_patch(src, old, new)
    assert applied, f"{task['name']} 注入点没找到"
    p.write_text(new_src, encoding="utf-8")
    return dst


def run_tests(repo: Path) -> tuple[bool, str]:
    p = subprocess.run([PY, "-m", "pytest", "tests/test_task.py", "-q", "--no-header"],
                       cwd=repo, capture_output=True, text=True, encoding="utf-8",
                       errors="replace",
                       env={**__import__("os").environ, "PYTHONPATH": str(repo),
                            "PYTHONIOENCODING": "utf-8"})
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0, out[-1200:]


def build_context(method: str, repo: Path, task: dict, fail_out: str, memory, history):
    q = f"{task['file']} 里的 bug 怎么修？测试失败：{fail_out[:200]}"
    target = repo / "ctxfold" / task["file"]
    if method == "full":
        head = f"[文件 {task['file']}]\n" + target.read_text(encoding="utf-8")
        return head + f"\n\n[历史]\n" + "\n".join(history[-2:]), None
    if method == "grepriag":
        chunks, index, sha = load_corpus(repo / "ctxfold")
        bm25 = BM25(chunks)
        got = bm25.top_k(q, k=5, budget=BUDGET)
        head = "\n\n".join(f"### #{c.cid} | {c.path}:{c.start}-{c.end}\n{c.text}" for c in got)
        return head + f"\n\n[历史]\n" + "\n".join(history[-2:]), None
    st = ours_state(repo)
    out = st.assemble(q)
    prompt = out["prompt"] + "\n\n[按 id 取回的原文]\n" + recall_file_text(st, task, fail_out)
    return prompt, ("ours", st)


def apply_patch(src: str, old: str, new: str) -> tuple[str, bool]:
    """先精确替换；不行就按"去掉首尾空白后逐行比对"的窗口替换（模型常多带缩进）。"""
    if old in src:
        return src.replace(old, new, 1), True
    old_lines = [ln.strip() for ln in old.splitlines() if ln.strip()]
    if not old_lines:
        return src, False
    src_lines = src.splitlines(keepends=True)
    n = len(old_lines)
    for i in range(len(src_lines) - n + 1):
        window = [ln.strip() for ln in src_lines[i:i + n]]
        if window == old_lines:
            indent = src_lines[i][: len(src_lines[i]) - len(src_lines[i].lstrip())]
            new_lines = [indent + ln.strip() for ln in new.splitlines() if ln.strip()] or [""]
            return "".join(src_lines[:i]) + "\n".join(new_lines) + "\n" + "".join(src_lines[i + n:]), True
    return src, False


def ask_patch(context: str) -> tuple[dict | None, int, int]:
    sys_prompt = ("你是代码修复助手。只返回一个 JSON 对象："
                  '{"old": "仓库里原样存在的片段", "new": "替换后的片段"}，不要解释。')
    resp = llm.chat([{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": context}], max_tokens=700)
    msg = resp["choices"][0]["message"].get("content") or ""
    usage = resp.get("usage") or {}
    try:
        m = re.search(r"\{.*\}", msg, re.S)
        data = json.loads(m.group(0)) if m else None
    except Exception:
        data = None
    return data, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def run_task(method: str, task: dict) -> dict:
    repo = build_repo(task)
    memory: dict = {}
    history: list[str] = []
    tokens = 0
    steps = 0
    invalidations: list[int] = []
    t0 = time.time()
    ok, fail_out = run_tests(repo)
    while not ok and steps < MAX_STEPS:
        steps += 1
        context, ours_ctx = build_context(method, repo, task, fail_out, memory, history)
        patch, up, uc = ask_patch(context)
        tokens += token_count(context) + up + uc
        if not patch or not isinstance(patch.get("old"), str):
            history.append("[补丁解析失败]")
            continue
        target = repo / "ctxfold" / task["file"]
        src = target.read_text(encoding="utf-8")
        new_src, applied = apply_patch(src, patch["old"], patch.get("new", ""))
        if os.environ.get("CTX_M22_DEBUG"):
            print(f"  [dbg step{steps}] applied={applied} old={patch['old'][:120]!r} "
                  f"new={str(patch.get('new',''))[:120]!r}", flush=True)
            print(f"  [dbg fail] {fail_out[-400:]}", flush=True)
        if not applied:
            history.append("[old 片段未找到]")
            continue
        target.write_text(new_src, encoding="utf-8")
        # ours：改完后统计失效（按哈希，装配前）
        if method == "ours":
            st = ours_state(repo)
            info = st.invalidate()
            invalidations.append(len(info["invalidated"]) + len(info["downstream"]))
        ok, fail_out = run_tests(repo)
        history.append(f"[第{steps}步] 修复尝试，测试{'通过' if ok else '仍失败'}")
    return {"method": method, "task": task["name"], "passed": ok, "steps": steps,
            "tokens": tokens, "seconds": round(time.time() - t0, 1),
            "invalidations": invalidations}


def main() -> int:
    methods = sys.argv[1].split(",") if len(sys.argv) > 1 else ["full", "grepriag", "ours"]
    only = [x.strip() for x in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if x.strip()]
    rows = []
    for task in TASKS:
        if only and not any(x in task["name"] for x in only):
            continue
        probe_repo = build_repo(task)
        bad, _ = run_tests(probe_repo)
        if os.environ.get("CTX_M22_PRECHECK"):
            print(f"{task['name'][:24]:24s} {'不可观测(跳过)' if bad else '可观测'}", flush=True)
            continue
        if bad:
            print(f"{task['name'][:22]:22s} [SKIP] 注入 bug 后测试仍通过，任务无效", flush=True)
            continue
        for m in methods:
            try:
                r = run_task(m, task)
            except Exception as e:
                print(f"{task['name'][:22]} {m} [ERROR] {type(e).__name__}: {e}", flush=True)
                continue
            rows.append(r)
            print(f"{task['name'][:22]:22s} {m:9s} 通过={r['passed']} 步数={r['steps']} "
                  f"token={r['tokens']:6d} 耗时={r['seconds']:5.1f}s 失效={r['invalidations']}", flush=True)
    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m22")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(
        {"manifest": {"max_steps": MAX_STEPS, "budget": BUDGET, "methods": methods,
                      "tasks": [t["name"] for t in TASKS]}, "rows": rows},
        ensure_ascii=False, indent=2), "utf-8")
    print("run dir:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
