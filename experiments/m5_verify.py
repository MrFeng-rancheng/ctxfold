"""M5 动态抽检实验（离线）：结论带可执行校验器时，抽检真的能发现"推错了"。

设计：
  - 建一个小仓库 + 3 条结论：2 条正确、1 条故意写错；
  - 每条都带可执行校验器（python -c "assert ..."）；
  - 抽检全部执行，看 E（错误残留率）能否把那条错的揪出来；
  - 同时测每次动态校验的耗时，和静态校验对比。

诚实边界：只有**能写出可执行校验器**的结论才能被动态验证。
写不出来的（"这个方案更好"）仍然退回静态校验，而静态校验发现不了"推错了"。
"""
from __future__ import annotations

import json
import statistics as st
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.runtime import Runtime  # noqa: E402

SRC = '''def add(a, b):
    return a + b


def is_adult(age):
    return age >= 18
'''


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ctxfold-verify-"))
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(SRC, encoding="utf-8")

    rt = Runtime(corpus=repo, state_dir=tmp / "st", gate_interval=99)
    rt.ask("add 是怎么工作的？它调用了什么？")
    rt.ask("is_adult 是怎么工作的？它调用了什么？")
    cids = list(rt.memory)
    print(f"初始记忆 {len(cids)} 条: {cids}")

    py = sys.executable
    prefix = "import sys; sys.path.insert(0, '.'); from calc import "

    def probe(code: str) -> dict:
        return {"kind": "cmd", "cmd": [py, "-c", prefix + code]}

    claims = [
        ("add(1,1)==2", probe("add; assert add(1, 1) == 2"), True),
        ("is_adult(20) is True", probe("is_adult; assert is_adult(20) is True"), True),
        ("is_adult(20) is False（错误结论）", probe("is_adult; assert is_adult(20) is False"), False),
    ]
    # 每条结论挂到不同 cid 上（不能都塞给同一个，否则互相覆盖）
    mapping = [c for c in cids if c.endswith("::add")], [c for c in cids if c.endswith("::is_adult")]
    targets = [mapping[0][0], mapping[1][0], mapping[1][0]]
    for (claim, verifier, _ok), cid in zip(claims, targets):
        rt.remember(cid, claim, verifier)

    t0 = time.perf_counter()
    res = rt.audit_sample(rate_override=1.0)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"\n抽检 {res['audited']} 条，判错 {res['failed']} 条，E={res['E']:.3f}，"
          f"耗时 {elapsed:.0f}ms（每条约 {elapsed / max(1, res['audited']):.0f}ms）")
    for cid, mem in rt.memory.items():
        print(f"  [{mem.status:5}] {mem.claim[:40]:<42} verifier={'cmd' if mem.verifier else 'static'}")

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m5-verify")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "manifest": {"kind": "m5-verify (offline demo, synthetic claims)",
                     "memory": len(rt.memory), "claims": len(claims)},
        "audited": res["audited"],
        "failed": res["failed"],
        "E": res["E"],
        "ms_total": round(elapsed, 1),
        "ms_per_verify": round(elapsed / max(1, res["audited"]), 1),
        "stale_after": sum(1 for m in rt.memory.values() if m.status == "stale"),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nrun dir: {out}")
    return 0 if res["failed"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
