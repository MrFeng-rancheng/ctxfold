"""聚合多个 m22 run 目录（重复采样）：按方法给通过率、token、步数、耗时、失效条数。

用法：
  python experiments/agg_m22_multi.py                # 自动取干净批次（>= 20261123-013703）
  python experiments/agg_m22_multi.py 20261123-01    # 只取名字含该前缀的 run
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLEAN_FROM = "20261123-013703"      # pytest + 报错解码修好之后
ORDER = ("full", "grepriag", "ours")


def load(prefix: str) -> list[dict]:
    rows: list[dict] = []
    for d in sorted((ROOT / "experiments" / "runs").glob("*-m22")):
        name = d.name.split("-m22")[0]
        if prefix and prefix not in d.name:
            continue
        if not prefix and name < CLEAN_FROM:
            continue
        f = d / "summary.json"
        if not f.is_file():
            continue
        for r in json.loads(f.read_text("utf-8"))["rows"]:
            r["run"] = name
            rows.append(r)
    return rows


def main() -> int:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    rows = load(prefix)
    if not rows:
        print("没有可聚合的 run")
        return 1
    runs = sorted({r["run"] for r in rows})
    tasks = sorted({r["task"] for r in rows}, key=lambda s: int(s.split()[0][1:]))
    methods = [m for m in ORDER if any(r["method"] == m for r in rows)]
    reps = {m: max(sum(1 for r in rows if r["method"] == m and r["task"] == t) for t in tasks)
            for m in methods}

    print(f"run 目录（{len(runs)} 个）：" + "、".join(runs))
    print(f"任务 {len(tasks)} 个，方法 {len(methods)} 个，每格重复 {reps}\n")

    print("逐任务通过次数（通过/重复）：")
    print(f"{'任务':26s}" + "".join(f"{m:>12s}" for m in methods))
    for t in tasks:
        line = f"{t:26s}"
        for m in methods:
            rs = [r for r in rows if r["task"] == t and r["method"] == m]
            line += f"{(str(sum(1 for r in rs if r['passed'])) + '/' + str(len(rs))):>12s}"
        print(line)

    print("\n按方法汇总：")
    print(f"{'方法':10s}{'n':>4s}{'通过':>6s}{'通过率':>8s}{'token均值':>11s}{'token中位':>11s}"
          f"{'步数均值':>9s}{'耗时均值':>10s}{'失效/run':>10s}")
    for m in methods:
        rs = [r for r in rows if r["method"] == m]
        n, p = len(rs), sum(1 for r in rs if r["passed"])
        tk = [r["tokens"] for r in rs]
        print(f"{m:10s}{n:4d}{p:6d}{p / n:8.3f}{statistics.mean(tk):11.0f}"
              f"{statistics.median(tk):11.0f}{statistics.mean([r['steps'] for r in rs]):9.2f}"
              f"{statistics.mean([r['seconds'] for r in rs]):10.1f}"
              f"{sum(len(r['invalidations']) for r in rs) / n:10.2f}")

    # 每任务取多数通过的稳定解集
    stable = {t for t in tasks
              if sum(1 for r in rows if r["task"] == t and r["method"] == "full" and r["passed"]) > 0}
    print(f"\nfull 至少一次通过的任务：{len(stable)} 个")
    print(f"{'方法':10s}{'n':>4s}{'通过率':>8s}{'token均值':>11s}")
    for m in methods:
        rs = [r for r in rows if r["method"] == m and r["task"] in stable]
        if not rs:
            continue
        p = sum(1 for r in rs if r["passed"])
        print(f"{m:10s}{len(rs):4d}{p / len(rs):8.3f}{statistics.mean([r['tokens'] for r in rs]):11.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
