# -*- coding: utf-8 -*-
"""把三条验收契约跑一遍并打印人能读的证据（不需要 pytest）。"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.state import StateRuntime  # noqa: E402

FILES = {
    "base.py": "def add(a, b):\n    return a + b\n",
    "mid.py": "from base import add\n\n\ndef total(xs):\n    s = 0\n    for x in xs:\n        s = add(s, x)\n    return s\n",
    "top.py": "from mid import total\n\n\ndef average(xs):\n    if not xs:\n        return 0\n    return total(xs) / len(xs)\n",
    "other.py": "def unrelated(x):\n    return x * 2\n",
}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ctxfold-contract-"))
    repo = tmp / "repo"
    repo.mkdir()
    for name, body in FILES.items():
        (repo / name).write_text(body, encoding="utf-8")

    print("=" * 68)
    print("契约 1：删掉 Skill 提示词后，核心照常运行")
    print("=" * 68)
    skill = ROOT / "skill"
    backup = tmp / "skill-backup"
    if skill.exists():
        shutil.move(str(skill), str(backup))
        print(f"  已把 {skill.name}/ 整个目录移走（模拟停用）")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ctxfold.cli", "--corpus", str(repo),
             "--state", str(tmp / "st1"), "ask", "add 是怎么实现的"],
            capture_output=True, text=True, encoding="utf-8",
            env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src"),
                 "CTXFOLD_SKILL_DIR": str(tmp / "deleted-skill")},
        )
        ok = proc.returncode == 0 and "[问题]" in proc.stdout
        print(f"  CLI 退出码 {proc.returncode}，装配成功={ok}")
        print("  装配输出前 3 行：")
        for line in proc.stdout.strip().splitlines()[:3]:
            print("   ", line[:88])
    finally:
        if backup.exists():
            shutil.move(str(backup), str(skill))
            print(f"  已把 {skill.name}/ 恢复")

    st = StateRuntime(repo, tmp / "st2")
    print()
    print("=" * 68)
    print("契约 2：raw 块带出处头，占位符可按 ID 取回")
    print("=" * 68)
    first = st.assemble("add 是怎么实现的")
    for b in first["raw_blocks"]:
        print("  raw:", b["header"])
    second = st.assemble("add 是怎么实现的")
    print(f"  第二轮 levels={second['levels']}")
    for cid in second["placeholders"][:3]:
        r = st.recall(cid)
        print(f"  recall {cid}: unchanged={r['unchanged']} 首行={r['text'].splitlines()[0][:40]!r}")

    print()
    print("=" * 68)
    print("契约 3：改一个符号 -> 失效 + 下游波及 + 其余复用")
    print("=" * 68)
    add_cid = next(c for c in st.rt.by_cid if c.endswith("::add"))
    total_cid = next(c for c in st.rt.by_cid if c.endswith("::total"))
    other_cid = next(c for c in st.rt.by_cid if c.endswith("::unrelated"))
    st.assemble("total 是怎么实现的")
    st.assemble("unrelated 是怎么实现的")
    st.commit(total_cid, "total 对列表求和")
    st.commit(other_cid, "unrelated 乘二")
    print(f"  改动前记忆 {len(st.rt.memory)} 条，结论 {len(st.C)} 条")
    (repo / "base.py").write_text("def add(a, b):\n    return a + b + 0\n    # changed\n", encoding="utf-8")
    res = st.invalidate()
    print(f"  invalidated={res['invalidated']}")
    print(f"  downstream={res['downstream']}")
    print(f"  kept={res['kept']}")
    after = st.assemble("add 是怎么实现的")
    print(f"  改动后重读的 raw={[b['cid'] for b in after['raw_blocks']]}")
    print(f"  未改动符号是否被重发原文：{other_cid in {b['cid'] for b in after['raw_blocks']}}")
    print()
    print(json.dumps({"ok": True, "tmp": str(tmp)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
