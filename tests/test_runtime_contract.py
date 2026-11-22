"""三条验收契约的自动化测试。

1. 删掉/停用 Skill 提示词后，核心状态机与装配依然能独立运行；
2. 每个 raw 块都带 `### #<cid> | <file>:<start>-<end>` 出处头，每个 placeholder 都能按 ID 取回原文；
3. 改动某符号后，对应结论失效、下游被波及，未改动部分继续复用。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ctxfold.state import StateRuntime  # noqa: E402

HEADER_RE = re.compile(r"^### #(?P<cid>[^\s|]+) \| (?P<path>[^:]+):(?P<start>\d+)-(?P<end>\d+)$")

FILES = {
    "base.py": "def add(a, b):\n    return a + b\n",
    "mid.py": "from base import add\n\n\ndef total(xs):\n    s = 0\n    for x in xs:\n        s = add(s, x)\n    return s\n",
    "top.py": "from mid import total\n\n\ndef average(xs):\n    if not xs:\n        return 0\n    return total(xs) / len(xs)\n",
    "other.py": "def unrelated(x):\n    return x * 2\n",
}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    for name, body in FILES.items():
        (r / name).write_text(body, encoding="utf-8")
    return r


def cid_of(state: StateRuntime, keyword: str) -> str:
    hits = [c for c in state.rt.by_cid if c.split("::")[-1] == keyword]
    assert hits, f"找不到符号 {keyword}"
    return hits[0]


# ---------------- 契约 1：与 Skill 提示词解耦 ----------------
def test_core_has_no_skill_dependency(repo, tmp_path):
    # (a) 核心源码不读取任何提示词文件、也不认 skill 目录/环境变量
    files = list((SRC / "ctxfold").glob("*.py"))
    src_text = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert "skill/" not in src_text, "核心模块引用了 skill/ 目录"
    assert "CTXFOLD_SKILL" not in src_text, "核心模块认了 skill 环境变量"
    assert not re.search(r"open\([^)]*\.md", src_text), "核心模块直接读了 .md 提示词文件"
    assert not re.search(r"read_text\([^)]*\.md", src_text), "核心模块直接读了 .md 提示词文件"

    # (b) 把 skill 目录整个删掉、并指向一个不存在的路径，CLI 照样能装配
    fake_skill = tmp_path / "skill-copy"
    shutil.copytree(ROOT / "skill", fake_skill)
    shutil.rmtree(fake_skill)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["CTXFOLD_SKILL_DIR"] = str(fake_skill)      # 已被删掉，等于"停用"
    proc = subprocess.run(
        [sys.executable, "-m", "ctxfold.cli", "--corpus", str(repo),
         "--state", str(tmp_path / "st"), "ask", "add 是怎么实现的"],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "[问题]" in proc.stdout

    # (c) stdio 服务同样不依赖提示词
    st = StateRuntime(repo, tmp_path / "st2")
    out = st.assemble("add 是怎么实现的")
    assert out["prompt"].strip()


# ---------------- 契约 2：出处头 + 按 ID 取回 ----------------
def test_origin_headers_and_recall(repo, tmp_path):
    st = StateRuntime(repo, tmp_path / "st")
    first = st.assemble("add 是怎么实现的")
    assert first["raw_blocks"], "第一轮应当给出原文块"

    for block in first["raw_blocks"]:
        m = HEADER_RE.match(block["header"])
        assert m, f"出处头格式不对: {block['header']}"
        assert m.group("cid") == block["cid"]
        assert (int(m.group("start")), int(m.group("end"))) == (block["start"], block["end"])
        assert block["header"] in first["prompt"], "出处头必须真的出现在 prompt 里"

    # 再问一次：应出现占位符/卡片/结论，且都能按 ID 取回原文
    second = st.assemble("add 是怎么实现的")
    assert second["placeholders"] or any(v != "raw" for v in second["levels"].values())
    for cid in second["placeholders"]:
        r = st.recall(cid)
        assert r["text"] == st.rt.by_cid[cid].text
        assert r["header"].startswith("### #")
        assert r["unchanged"] is True

    # 从未进入过记忆的符号也能按 ID 取回（占位符语义）
    any_cid = next(iter(st.rt.by_cid))
    assert st.recall(any_cid)["text"]


def test_recall_survives_file_change(repo, tmp_path):
    """文件改了之后，recall 仍能取回当初那段（快照），并明确告知 unchanged=False。"""
    st = StateRuntime(repo, tmp_path / "st")
    st.assemble("add 是怎么实现的")
    add_cid = cid_of(st, "add")
    before = st.rt.by_cid[add_cid].text

    (repo / "base.py").write_text("def add(a, b):\n    return a + b + 0\n    # changed\n", encoding="utf-8")
    st.rt.load()                       # 让内存里的 chunk 反映新文件
    after = st.recall(add_cid)
    assert after["text"] == before, "应取回固化时的原文（快照）"
    assert after["source"] == "snapshot"
    assert after["unchanged"] is False, "文件已变，必须标记 unchanged=False"
    assert after["current_text"] != before


# ---------------- 契约 3：失效传播与复用 ----------------
def test_invalidation_propagates_and_reuse_holds(repo, tmp_path):
    st = StateRuntime(repo, tmp_path / "st")
    add_cid = cid_of(st, "add")
    total_cid = cid_of(st, "total")
    other_cid = cid_of(st, "unrelated")

    # 先把三个符号都拉进记忆
    st.assemble("add 是怎么实现的")
    st.assemble("total 是怎么实现的")
    st.assemble("unrelated 是怎么实现的")
    st.commit(total_cid, "total 求和")
    st.commit(other_cid, "unrelated 乘二")
    before = set(st.rt.memory)

    # 改掉 add 的函数体
    (repo / "base.py").write_text("def add(a, b):\n    return a + b + 0\n    # changed\n", encoding="utf-8")

    res = st.invalidate()
    assert add_cid in res["invalidated"], f"改动的符号应被判失效，实际 {res}"
    assert total_cid in res["downstream"], f"依赖它的下游应被波及，实际 {res}"
    assert other_cid in res["kept"], f"无关符号应继续复用，实际 {res}"

    # 重新装配：被改的符号回到 raw（重读原文），无关符号仍是固化状态
    after = st.assemble("add 是怎么实现的")
    head = {b["cid"] for b in after["raw_blocks"]}
    assert add_cid in head, "失效后应重读原文"
    assert other_cid not in head, "未改动部分不应重发原文（应当复用）"
    assert set(st.rt.memory) >= before
