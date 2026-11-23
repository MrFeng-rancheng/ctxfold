"""聚合 m22 多步编码任务结果：读 run 目录 summary.json，输出按方法的通过率/token/步数/耗时。"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    runs = sorted((ROOT / "experiments" / "runs").glob("*-m22"))
    if len(sys.argv) > 1:
        runs = [r for r in runs if sys.argv[1] in r.name]
    run = runs[-1]
    data = json.loads((run / "summary.json").read_text("utf-8"))
    rows = data["rows"]
    print(f"run dir: {run.name}  行数={len(rows)}  任务数={len(data['manifest']['tasks'])}")
    print(f"MAX_STEPS={data['manifest']['max_steps']} BUDGET={data['manifest']['budget']}\n")

    tasks = sorted({r["task"] for r in rows}, key=lambda s: int(s.split()[0][1:]))
    methods = [m for m in ("full", "grepriag", "ours") if any(r["method"] == m for r in rows)]

    print("逐任务（通过 / token / 步数）：")
    head = f"{'任务':26s}" + "".join(f"{m:>22s}" for m in methods)
    print(head)
    for t in tasks:
        line = f"{t:26s}"
        for m in methods:
            r = next((x for x in rows if x["task"] == t and x["method"] == m), None)
            if r is None:
                line += f"{'—':>22s}"
            else:
                mark = "✓" if r["passed"] else "✗"
                line += f"{mark + str(r['tokens']):>13s}/{r['steps']:<6d}"[:22].rjust(22)
        print(line)

    print("\n按方法汇总（n = 该方法有结果的 run 数）：")
    print(f"{'方法':10s}{'n':>4s}{'通过':>6s}{'通过率':>8s}{'token均值':>11s}{'token中位':>11s}"
          f"{'步数均值':>9s}{'耗时均值':>10s}{'失效合计':>9s}")
    for m in methods:
        rs = [r for r in rows if r["method"] == m]
        if not rs:
            continue
        n = len(rs)
        p = sum(1 for r in rs if r["passed"])
        tk = [r["tokens"] for r in rs]
        print(f"{m:10s}{n:4d}{p:6d}{p / n:8.3f}{statistics.mean(tk):11.0f}"
              f"{statistics.median(tk):11.0f}{statistics.mean([r['steps'] for r in rs]):9.2f}"
              f"{statistics.mean([r['seconds'] for r in rs]):10.1f}"
              f"{sum(sum(r['invalidations']) for r in rs):9d}")

    # 可解子集：full 通过的任务视为"可从上下文定位"
    solvable = {r["task"] for r in rows if r["method"] == "full" and r["passed"]}
    print(f"\n可解子集（full 通过）：{len(solvable)} 个任务 -> " + "、".join(
        sorted(solvable, key=lambda s: int(s.split()[0][1:]))))
    for m in methods:
        rs = [r for r in rows if r["method"] == m and r["task"] in solvable]
        if not rs:
            continue
        p = sum(1 for r in rs if r["passed"])
        print(f"  {m:9s} n={len(rs):2d} 通过={p:2d} ({p / len(rs):.3f}) "
              f"token均值={statistics.mean([r['tokens'] for r in rs]):7.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
