"""核心自测（不依赖 pytest，直接 python tests/test_core.py）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.audit import Auditor  # noqa: E402
from ctxfold.chunker import Chunk, build_symbol_index, chunk_repo  # noqa: E402
from ctxfold.ledger import Ledger  # noqa: E402
from ctxfold.world import cheap_fingerprint, content_fingerprint  # noqa: E402


def test_chunker(tmp: Path) -> None:
    (tmp / "m.py").write_text(
        "def a(x):\n    return b(x)\n\ndef b(x):\n    return x + 1\n", encoding="utf-8"
    )
    chunks = chunk_repo(tmp)
    names = sorted(c.name for c in chunks)
    assert names == ["a", "b"], names
    idx = build_symbol_index(chunks)
    assert set(idx) == {"a", "b"}
    assert idx["a"] == ["m.py::a"], "同名多候选必须保留全部 cid"
    c = [c for c in chunks if c.name == "a"][0]
    assert "b" in c.calls, c.calls
    assert c.text_sha == c.text_sha and len(c.text_sha) == 16


def test_ledger(tmp: Path) -> None:
    led = Ledger(tmp / "l.jsonl")
    led.append("commit", "A")
    led.append("commit", "B")
    led.append("stale", "A", reason="file_hash")
    assert led.replay() == {"A": "stale", "B": "fresh"}
    n = led.rollback_to(2)
    assert n == 2
    assert led.replay() == {"A": "fresh", "B": "fresh"}
    assert led.summary()["commit"] == 2
    try:
        led.append("bogus")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown kind must raise")


def test_world(tmp: Path) -> None:
    f = tmp / "a.py"
    f.write_text("x = 1" + chr(10), encoding="utf-8")
    c1, k1 = cheap_fingerprint(tmp), content_fingerprint(tmp)
    assert c1 == cheap_fingerprint(tmp) and k1 == content_fingerprint(tmp), "no change must be stable"

    import os
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert cheap_fingerprint(tmp) != c1, "mtime changed -> cheap must report (false positive is fine)"
    assert content_fingerprint(tmp) == k1, "content unchanged -> content fp must not report"

    f.write_text("x = 2" + chr(10), encoding="utf-8")
    assert content_fingerprint(tmp) != k1, "content changed must be reported"

def test_auditor() -> None:
    a = Auditor(rate=0.5, salt="t")
    a1 = [c for c in ("x", "y", "z", "w") if a.should_audit(c)]
    a2 = [c for c in ("x", "y", "z", "w") if Auditor(rate=0.5, salt="t").should_audit(c)]
    assert a1 == a2, "抽检必须确定性可复现"
    assert isinstance(a1, list)
    assert a.error_rate is None, "无抽检时不得谎报 0"
    a.record("x", "fail", "test")
    a.record("y", "pass", "test")
    assert a.audited == 2 and a.failed == 1 and a.error_rate == 0.5
    assert a.escalate(0.1) is True


def test_assembler_placeholder(tmp: Path) -> None:
    chunks = [
        Chunk("m.py::f", "m.py", "f", "function", 1, 2, "def f():\n    return 1", 10, "sha1"),
        Chunk("m.py::g", "m.py", "g", "function", 4, 5, "def g():\n    return 2", 10, "sha1"),
    ]
    chunks[0].__dict__["deps"] = ["m.py::g"]
    by_cid = {c.cid: c for c in chunks}
    index = {"f": ["m.py::f"], "g": ["m.py::g"]}
    mem = {}

    r1 = assemble(
        "ours", "f 怎么工作？", [], by_cid, index, mem, {"m.py": "sha1"}, budget=1000
    )
    assert "m.py::f" in r1.included_cids and "m.py::g" in r1.included_cids, r1.included_cids
    assert r1.no_model_needed is False

    # 第二次问同一个符号：应全部命中占位符 => 免算
    r2 = assemble(
        "ours", "f 怎么工作？", [r1.history_append], by_cid, index, mem, {"m.py": "sha1"}, budget=1000
    )
    assert r2.no_model_needed is True, r2.decisions
    assert r2.prompt.count("[") >= 1 and not r2.included_cids

    # 文件变了（symbol guard 不变）：仍可复用
    r3 = assemble(
        "ours", "f 怎么工作？", [], by_cid, index, mem, {"m.py": "sha999"}, budget=1000, guard_level="file"
    )
    assert not r3.no_model_needed, "file 级 guard 应判定失效"


def test_runtime_audit(tmp: Path) -> None:
    from ctxfold.runtime import Runtime

    repo = tmp / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(x):" + chr(10) + "    return g(x)" + chr(10) + chr(10)
                              + "def g(x):" + chr(10) + "    return x + 1" + chr(10), encoding="utf-8")
    rt = Runtime(corpus=repo, state_dir=tmp / "st", gate_interval=99)  # 门几乎不查
    rt.ask("f 是怎么工作的？")
    assert len(rt.memory) >= 1

    (repo / "a.py").write_text("def f(x):" + chr(10) + "    return g(x) + 100" + chr(10) + chr(10)
                              + "def g(x):" + chr(10) + "    return x + 1" + chr(10), encoding="utf-8")
    res = rt.audit_sample(rate_override=1.0)
    assert res["audited"] >= 1 and res["failed"] >= 1, res
    assert any(m.status == "stale" for m in rt.memory.values()), "抽检必须把漂移的结论标 stale"

def test_dynamic_verify(tmp: Path) -> None:
    """动态抽检：结论带可执行校验器时，抽中即真跑一遍。"""
    from ctxfold.runtime import Runtime

    repo = tmp / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):" + chr(10) + "    return a + b" + chr(10), encoding="utf-8")
    rt = Runtime(corpus=repo, state_dir=tmp / "st", gate_interval=99)
    rt.ask("add 是怎么工作的？")
    assert rt.memory, "应先固化至少一条记忆"
    cid = next(iter(rt.memory))

    probe_ok = [sys.executable, "-c",
                "import sys; sys.path.insert(0, '.'); from calc import add; assert add(1, 1) == 2"]
    probe_bad = [sys.executable, "-c",
                 "import sys; sys.path.insert(0, '.'); from calc import add; assert add(1, 1) == 3"]

    rt.remember(cid, "add(1,1)==2", {"kind": "cmd", "cmd": probe_ok})
    res = rt.audit_sample(rate_override=1.0)
    assert res["failed"] == 0, res

    rt.remember(cid, "add(1,1)==3（错误结论）", {"kind": "cmd", "cmd": probe_bad})
    res = rt.audit_sample(rate_override=1.0)
    assert res["failed"] >= 1, res
    assert res["E"] and res["E"] > 0, res
    assert any(m.status == "stale" for m in rt.memory.values()), "错误结论必须被标 stale"

def test_strict_visibility(tmp: Path) -> None:
    """strict_visibility=True 时，已固化内容也重发原文（可见性优先）。"""
    from ctxfold.runtime import Runtime

    repo = tmp / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def f(x):" + chr(10) + "    return x + 1" + chr(10), encoding="utf-8")
    q = "f 是怎么工作的？"

    rt = Runtime(corpus=repo, state_dir=tmp / "loose", strict_visibility=False)
    rt.ask(q)
    loose = rt.ask(q)
    assert loose["placeholders"] or loose["included"], "非 strict 应有卡片或占位符"

    rt2 = Runtime(corpus=repo, state_dir=tmp / "strict", strict_visibility=True)
    rt2.ask(q)
    strict = rt2.ask(q)
    assert strict["included"], "strict 必须重发原文"
    assert not strict["placeholders"], "strict 不应出现占位符"

def test_doctor(tmp: Path) -> None:
    """doctor 必须能给出可用的诊断与建议。"""
    from ctxfold.doctor import diagnose, render

    repo = tmp / "repo"
    repo.mkdir()
    src = ""
    for i in range(6):
        body = "".join(
            f"    v{k} = f{max(0, i - 1)}(x) + {i} * {k}" + chr(10) for k in range(6)
        )
        src += f"def f{i}(x):" + chr(10) + body + "    return v5" + chr(10) + chr(10)
    (repo / "chain.py").write_text(src, encoding="utf-8")

    d = diagnose(repo, turns=8)
    assert d.chunks >= 6, d.chunks
    assert 0.0 <= d.loose_r_prompt <= 1.0 and 0.0 <= d.strict_r_prompt <= 1.0
    assert d.full_tokens > 0 and d.loose_tokens > 0
    assert isinstance(d.suggested_strict, bool)
    assert d.suggested_budget >= 800
    assert "仓库" in render(d)

def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_chunker(tmp / "a") if (tmp / "a").mkdir() is None else None
        test_ledger(tmp / "b") if (tmp / "b").mkdir() is None else None
        test_assembler_placeholder(tmp / "c") if (tmp / "c").mkdir() is None else None
    test_auditor()
    with tempfile.TemporaryDirectory() as d2:
        test_world(Path(d2))
    with tempfile.TemporaryDirectory() as d3:
        test_runtime_audit(Path(d3))
    with tempfile.TemporaryDirectory() as d4:
        test_dynamic_verify(Path(d4))
    with tempfile.TemporaryDirectory() as d5:
        test_strict_visibility(Path(d5))
    with tempfile.TemporaryDirectory() as d6:
        test_doctor(Path(d6))
    print("all core tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
