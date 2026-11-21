"""m10_ksweep：验证命题 3（复用收益条件）的阈值 k* = c_c / (c_c − c_r)。

做法：在同一语料上，让同一个问题被连续问 k 次（k = 1..12），分别统计
  · 不复用（full）：每轮都把原文重发；
  · 复用（ours）：第一轮读原文，之后走摘要卡/占位符。
实测累计 token 的节省率随 k 的变化，并与式(3) 给出的预测阈值对照。

用法：python experiments/m10_ksweep.py [--turns 60] [--corpus PATH]
产出：experiments/RESULTS-m10.md（自动生成，勿手改）
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from datetime import datetime
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import assemble      # noqa: E402
from ctxfold.chunker import load_corpus      # noqa: E402
from ctxfold.retrieve import BM25            # noqa: E402
from ctxfold.runtime import Memory           # noqa: E402
from ctxfold.tokenize import token_count     # noqa: E402

STDLIB = Path(__import__("sysconfig").get_paths()["stdlib"])


def one_k(chunks, index, sha, by_cid, bm25, k: int, budget: int = 1600):
    """同一个问题连问 k 次，返回 (full_tokens, ours_tokens, c_c, c_r)。"""
    pool = [c for c in chunks if c.tokens >= 40]
    target = pool[len(pool) // 2]
    query = f"{target.name} 是怎么工作的？它调用了什么？"

    full_tokens = 0
    ours_tokens = 0
    memory: dict[str, Memory] = {}
    history: list[str] = []
    first_raw = 0
    later = []
    for turn in range(k):
        full_tokens += target.tokens * (turn + 1)
        res = assemble("ours", query, history, by_cid, index, memory, sha, budget=budget)
        t = token_count(res.prompt)
        ours_tokens += t
        if turn == 0:
            first_raw = t
        else:
            later.append(t)
        history.append(res.history_append)

    c_c = first_raw if first_raw else target.tokens
    c_r = st.mean(later) if later else 0.0
    return full_tokens, ours_tokens, c_c, c_r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(STDLIB / "http"))
    ap.add_argument("--max-k", type=int, default=12)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    chunks, index, sha = load_corpus(corpus)
    by_cid = {c.cid: c for c in chunks}
    bm25 = BM25(chunks)

    rows = []
    for k in range(1, args.max_k + 1):
        f, o, c_c, c_r = one_k(chunks, index, sha, by_cid, bm25, k)
        saved = 1 - o / f if f else 0.0
        k_star = c_c / (c_c - c_r) if c_c > c_r else float("inf")
        rows.append({"k": k, "full": f, "ours": o, "saved": round(saved, 4),
                     "c_c": round(c_c, 1), "c_r": round(c_r, 1), "k_star": round(k_star, 2)})
        print(f"k={k:2d}  full={f:7d}  ours={o:7d}  saved={saved:6.1%}  "
              f"c_c={c_c:7.1f} c_r={c_r:6.1f} k*={k_star:5.2f}")

    out = ROOT / "experiments" / "RESULTS-m10.md"
    md = ["# 复用次数与净收益（m10，自动生成，勿手改）", "",
          f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}　语料：`{corpus}`", "",
          "| 复用次数 k | 不复用 token | 复用 token | 节省率 | 首次成本 c_c | 复用成本 c_r | 理论阈值 k* |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        md.append(f"| {r['k']} | {r['full']:,} | {r['ours']:,} | {r['saved']:.1%} | "
                  f"{r['c_c']:.0f} | {r['c_r']:.0f} | {r['k_star']:.2f} |")
    md += ["", "读法：节省率随 k 单调上升；k 小于理论阈值 k* 时，复用的固定投入尚未收回。"]
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n写入", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
