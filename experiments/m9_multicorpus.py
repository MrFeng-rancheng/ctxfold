"""m9_multicorpus：多语料 × 多种子的上下文策略对比（论文表 2 的数据来源）。

目的：回答"结论是不是只对某个代码库成立"。对每个语料跑同一套任务生成器与五个方法，
跨 10 个种子聚合，报告 C_cum / R_prompt / R_prompt_far 的均值±标准差。

用法：
    python experiments/m9_multicorpus.py                 # 默认 6 语料 × 10 种子 × 60 轮
    python experiments/m9_multicorpus.py --turns 40 --seeds 7,11,13

产出：
    experiments/runs/<ts>-m9/<corpus>.json   每个语料的聚合结果
    experiments/RESULTS-m9.md                人读的表格（自动生成，勿手改）
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
STDLIB = Path(__import__("sysconfig").get_paths()["stdlib"])

# 语料：标准库里体量递增的五个真实包 + 本项目自身源码
CORPORA = [
    ("stdlib/http", STDLIB / "http"),
    ("stdlib/json", STDLIB / "json"),
    ("stdlib/unittest", STDLIB / "unittest"),
    ("stdlib/email", STDLIB / "email"),
    ("stdlib/asyncio", STDLIB / "asyncio"),
    ("stdlib/collections", STDLIB / "collections"),
    ("stdlib/typing", STDLIB / "typing"),
    ("stdlib/logging", STDLIB / "logging"),
    ("stdlib/urllib", STDLIB / "urllib"),
    ("this-repo", ROOT / "src"),
]


def run_one(corpus: Path, turns: int, seed: int, tag: str) -> dict | None:
    cmd = [PY, "experiments/m2_baselines.py",
           "--corpus", str(corpus), "--turns", str(turns), "--seed", str(seed), "--tag", tag]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(f"  [FAIL] {tag} seed={seed}: {(p.stdout or p.stderr).strip().splitlines()[-1:]}")
        return None
    run_dir = None
    for line in (p.stdout or "").splitlines():
        if line.startswith("run dir: "):
            run_dir, _ = line[9:], True
        elif line.startswith("chunks="):
            print(f"  {tag} seed={seed}: {line}")
    if not run_dir:
        return None
    summary = json.loads((Path(run_dir) / "summary.json").read_text(encoding="utf-8"))
    return summary["table"]


def mean_sd(values: list[float]) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], 0.0)
    return (st.mean(values), st.stdev(values))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=100)
    ap.add_argument("--seeds", default="7,11,13,17,19,23,29,31,37,41,43,47,53,59,61,67,71,73,79,83")
    ap.add_argument("--only", default="", help="只跑某个语料（名字包含该字符串）")
    ap.add_argument("--out", default="", help="输出 md 路径（默认 experiments/RESULTS-m9.md）")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "experiments" / "runs" / f"{stamp}-m9"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, corpus in CORPORA:
        if args.only and args.only not in name:
            continue
        if not corpus.exists():
            print(f"[skip] {name}: {corpus} 不存在")
            continue
        print(f"\n=== {name} ({corpus}) ===")
        per_seed = []
        for seed in seeds:
            table = run_one(corpus, args.turns, seed, f"m9-{name.replace('/', '-')}-{seed}")
            if table:
                per_seed.append(table)
        if not per_seed:
            print(f"[warn] {name}: 无有效结果")
            continue

        agg = {}
        for method in ("full", "window", "summary", "grepriag", "compress", "memgpt", "ours"):
            agg[method] = {}
            for key in ("c_cum", "r_prompt", "r_avail", "r_prompt_far", "no_model_needed"):
                vals = [t[method][key] for t in per_seed]
                m, sd = mean_sd(vals)
                agg[method][key] = {"mean": round(m, 4), "sd": round(sd, 4), "n": len(vals)}
            agg[method]["total_tokens"] = {
                "mean": round(st.mean(t[method]["total_tokens"] for t in per_seed), 1),
                "sd": round(mean_sd([t[method]["total_tokens"] for t in per_seed])[1], 1),
            }
        n_chunks = per_seed[0]["ours"].get("chunks")
        rec = {
            "corpus": name,
            "path": str(corpus),
            "turns": args.turns,
            "seeds": seeds,
            "n_runs": len(per_seed),
            "chunks": n_chunks,
            "agg": agg,
        }
        (out_dir / f"{name.replace('/', '-')}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(rec)
        o = agg["ours"]
        print(f"  汇总 {name}: C_cum={o['c_cum']['mean']:.3f}±{o['c_cum']['sd']:.3f}  "
              f"R_prompt={o['r_prompt']['mean']:.3f}±{o['r_prompt']['sd']:.3f}  "
              f"token={o['total_tokens']['mean']:.0f}")

    if not rows:
        print("[FATAL] 没有任何结果")
        return 2

    md = [f"# 多语料实验（m9，自动生成，勿手改）", "",
          f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}　"
          f"轮数 {args.turns}　种子 {len(seeds)} 个　"
          f"tokenizer：`estimator:chars/3.5`（估算值，非真实 token）", "",
          "| 语料 | 方法 | 总 token | C_cum | R_prompt | R_prompt(长程) | R_avail |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for rec in rows:
        for method in ("full", "window", "summary", "grepriag", "compress", "memgpt", "ours"):
            a = rec["agg"][method]
            md.append("| {c} | {m} | {t:,.0f} | {c_cum:.3f}±{c_sd:.3f} | {r:.3f}±{r_sd:.3f} | "
                      "{rf:.3f}±{rf_sd:.3f} | {ra:.3f} |".format(
                          c=rec["corpus"], m=method,
                          t=a["total_tokens"]["mean"],
                          c_cum=a["c_cum"]["mean"], c_sd=a["c_cum"]["sd"],
                          r=a["r_prompt"]["mean"], r_sd=a["r_prompt"]["sd"],
                          rf=a["r_prompt_far"]["mean"], rf_sd=a["r_prompt_far"]["sd"],
                          ra=a["r_avail"]["mean"]))
    md += ["", "**读法**：`full` 是同一批任务的全量历史基线；C_cum 为累计 token 压缩率；",
           "R_prompt 为本轮 prompt 中可见的 gold 证据比例；R_avail 恒为 1.000 属定义使然（gold 与闭包同源），",
           "不作为性能主张。所有数字由 `experiments/reproduce.py` 重跑可复现。"]
    out_md = Path(args.out) if args.out else (ROOT / "experiments" / "RESULTS-m9.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    (out_dir / "aggregate.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps({"manifest": {"kind": "m9", "turns": args.turns, "seeds": seeds,
                               "corpora": [r["corpus"] for r in rows]},
                    "table": {"m9": {"corpora": len(rows), "runs": sum(r["n_runs"] for r in rows)}}},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写入 {out_md}，明细 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
