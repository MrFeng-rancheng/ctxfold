"""selftest_online：用本地假端点把 `m3_online.py --mode real` 的全链路跑一遍（零成本）。

目的：等真实 key 到位时，不会因为胶水 bug 白烧钱。
检查项：HTTP 往返、function calling（recall）、usage 记账、分题型统计、错误处理。

用法：python scripts/selftest_online.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from stub_server import serve  # noqa: E402

PORT = 8799
PY = sys.executable


def main() -> int:
    srv = serve(PORT)
    time.sleep(0.4)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONIOENCODING": "utf-8",
        "CTXFOLD_BASE_URL": f"http://127.0.0.1:{PORT}/v1",
        "CTXFOLD_API_KEY": "stub-key",
        "CTXFOLD_MODEL": "stub",
    }
    print("== 跑 m3_online --mode real 对着本地假端点 ==")
    p = subprocess.run(
        [PY, "experiments/m3_online.py", "--mode", "real", "--tasks", "2"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=env,
    )
    srv.shutdown()
    print(p.stdout[-2500:])
    if p.returncode != 0:
        print(p.stderr[-1500:])
        print("FAIL: 全链路未跑通")
        return 1

    # 找到刚生成的 run 目录并核对字段
    runs = sorted((ROOT / "experiments" / "runs").glob("*-m3-real"))
    if not runs:
        print("FAIL: 没生成 run 目录")
        return 1
    summary = json.loads((runs[-1] / "summary.json").read_text(encoding="utf-8"))
    checks = [
        ("A 存在", "A" in summary),
        ("H 存在", "H" in summary),
        ("recall_rate 存在", "recall_rate" in summary),
        ("分题型 A 存在", bool(summary.get("A_by_kind"))),
        ("usage 有记账", summary.get("usage_prompt_total", 0) > 0),
        ("manifest 不含 key", "key" not in json.dumps(summary.get("manifest", {})).lower()),
        ("recall 真的被触发过", summary.get("recall_rate", 0) > 0),
    ]
    ok = True
    for name, cond in checks:
        print(f"  {'[ok]  ' if cond else '[FAIL]'} {name}")
        ok = ok and cond
    print(f"\nrun dir: {runs[-1]}")
    print("全链路通过（零成本）" if ok else "存在问题")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
