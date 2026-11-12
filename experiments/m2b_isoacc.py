"""M2b 等精度切片（iso-accuracy）：protocol.md §3 要求的另一半对照。

问题：grep-RAG 的证据率能靠"多塞"追上 ctxfold 吗？追上的代价是多少 token？
做法：固定任务序列，对 grep-RAG 扫预算，记录 (总 token, R_avail)；
      与 ctxfold 在同一 R_avail 水平下比较 token 成本。
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.retrieve import BM25  # noqa: E402
from ctxfold.tasks import build_tasks  # noqa: E402
from ctxfold.tokenize import IS_ESTIMATE, TOKENIZER_NAME, token_count  # noqa: E402

DEFAULT_CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)


def run_grepriag(tasks, by_cid, bm25, budget, k):
    total, rows = 0, []
    for task in tasks:
        got = bm25.top_k(task["query"], k=k, budget=budget)
        prompt = "[检索证据]\n" + "\n\n".join(c.text for c in got) + f"\n\n[问题] {task['query']}"
        tok = token_count(prompt)
        total += tok
        gold = set(task["gold"])
        rows.append({"tokens": tok, "r": len(gold & {c.cid for c in got}) / len(gold)})
    return {"total_tokens": total, "r_avail": st.mean(r["r"] for r in rows),
            "max_tokens": max(r["tokens"] for r in rows)}


def run_ours(tasks, by_cid, index, sha, budget, recall_all: bool):
    memory: dict[str, Memory] = {}
    history: list[str] = []
    total, rows = 0, []
    for task in tasks:
        res = assemble("ours", task["query"], history, by_cid, index, memory, sha, budget=budget)
        history.append(res.history_append)
        tok = token_count(res.prompt)
        if recall_all:  # 悲观：每个占位符都被召回
            tok += sum(by_cid[c].tokens for c in res.placeholder_cids)
        total += tok
        gold = set(task["gold"])
        avail = set(res.included_cids) | set(res.placeholder_cids)
        rows.append({"tokens": tok, "r": len(gold & avail) / len(gold)})
    return {"total_tokens": total, "r_avail": st.mean(r["r"] for r in rows),
            "max_tokens": max(r["tokens"] for r in rows)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--turns", type=int, default=50)
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"[FATAL] corpus not found: {corpus}")
        return 2

    chunks, index, sha = load_corpus(corpus)
    by_cid = {c.cid: c for c in chunks}
    bm25 = BM25(chunks)
    tasks = build_tasks(chunks, args.turns, args.seed, locality=True, far_ref=0.4)

    target = run_ours(tasks, by_cid, index, sha, args.budget, recall_all=True)
    print(f"ctxfold（全量 recall）: tokens={target['total_tokens']:,} R_avail={target['r_avail']:.3f}")

    sweep = []
    for b in (1600, 2400, 3200, 4800, 6400, 9600, 12800, 19200):
        r = run_grepriag(tasks, by_cid, bm25, b, k=64)
        r["budget"] = b
        sweep.append(r)
        print(f"  grep-RAG budget={b:>6}: tokens={r['total_tokens']:>8,} R_avail={r['r_avail']:.3f}")

    hit = next((r for r in sweep if r["r_avail"] >= target["r_avail"]), None)
    result = {
        "manifest": {"corpus": str(corpus), "turns": args.turns, "seed": args.seed,
                     "tokenizer": TOKENIZER_NAME, "estimate": IS_ESTIMATE,
                     "budget_ctxfold": args.budget},
        "ctxfold": target,
        "grepriag_sweep": sweep,
        "iso_accuracy_hit": hit,
        "verdict": None,
    }
    if hit:
        ratio = hit["total_tokens"] / target["total_tokens"]
        result["verdict"] = {
            "grepriag_budget_needed": hit["budget"],
            "cost_ratio_vs_ctxfold": round(ratio, 2),
            "note": "等精度下 grep-RAG 的成本倍数；<1 表示我们更贵",
        }
        print(f"\n等精度点: grep-RAG budget={hit['budget']} → {hit['total_tokens']:,} token, "
              f"是 ctxfold 的 {ratio:.2f}×")
    else:
        print("\n在扫描范围内 grep-RAG 未达到 ctxfold 的证据率（说明其证据率存在上限）")

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m2b-isoacc")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(f"run dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
