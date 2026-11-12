"""M1 传播实验：一条结论失效后，"只重算受影响子图"到底省多少（纯离线）。

对比三种失效策略的重算成本：
  full      全部记忆失效（最保守，等于放弃状态）
  propagate 直接失效 + 沿 used_by 传播（本文主张）
  direct    只失效直接受影响项（不传播，有漏检风险）

注意（诚实边界）：
  传播的**精度**（"疑似污染"里有多少真的需要重算）离线无法测量，
  它取决于语义，只能靠在线抽检的 E 指标回答。这里只测**成本结构**。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import build_symbol_index, chunk_repo, load_corpus, resolve_dependencies  # noqa: E402
from ctxfold.ledger import Ledger  # noqa: E402

DEFAULT_CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)


def successors(used_by: dict[str, set[str]], seeds: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        cur = stack.pop()
        for nxt in used_by.get(cur, ()):  # 谁会因为 cur 的变化而需要重算
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--turns", type=int, default=40)
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"[FATAL] corpus not found: {corpus}")
        return 2

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-m1-propagation"
    out = ROOT / "experiments" / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(out / "ledger.jsonl")

    chunks, index, sha = load_corpus(corpus)
    by_cid = {c.cid: c for c in chunks}

    rng = random.Random(args.seed)
    pool = [c for c in chunks if c.tokens >= 40]
    rng.shuffle(pool)
    memory: dict[str, Memory] = {}
    history: list[str] = []
    for c in pool[: args.turns]:
        res = assemble(
            method="ours",
            query=f"{c.name} 是怎么工作的？它调用的东西是什么？",
            history=history,
            chunks_by_cid=by_cid,
            index=index,
            memory=memory,
            current_sha=sha,
            budget=args.budget,
        )
        history.append(res.history_append)

    for cid, mem in memory.items():
        ledger.append("commit", cid, chunk_sha=mem.chunk_sha, name=mem.name)

    # 依赖图：cid 变了 -> 谁需要重算
    used_by: dict[str, set[str]] = {}
    for cid in memory:
        for dep in by_cid[cid].__dict__.get("deps", []):
            if dep in memory:
                used_by.setdefault(dep, set()).add(cid)

    edges = sum(len(v) for v in used_by.values())
    nodes_with_out = len(used_by)

    # 成本统计
    cost_all = sum(by_cid[c].tokens for c in memory)
    trials = {1: [], 2: [], 3: []}
    for k in (1, 2, 3):
        for _ in range(args.trials):
            seeds = rng.sample(sorted(memory), min(k, len(memory)))
            suspect = successors(used_by, seeds) - set(seeds)
            cost_prop = sum(by_cid[c].tokens for c in set(seeds) | suspect)
            cost_direct = sum(by_cid[c].tokens for c in seeds)
            trials[k].append(
                {
                    "direct": len(seeds),
                    "suspect": len(suspect),
                    "cost_prop": cost_prop,
                    "cost_direct": cost_direct,
                    "cost_all": cost_all,
                }
            )

    table = {}
    for k, rows in trials.items():
        table[k] = {
            "suspect_mean": round(statistics.mean(r["suspect"] for r in rows), 2),
            "suspect_max": max(r["suspect"] for r in rows),
            "cost_all": cost_all,
            "cost_prop_mean": round(statistics.mean(r["cost_prop"] for r in rows), 1),
            "cost_prop_max": max(r["cost_prop"] for r in rows),
            "cost_direct_mean": round(statistics.mean(r["cost_direct"] for r in rows), 1),
            "saving_vs_full": round(1 - statistics.mean(r["cost_prop"] for r in rows) / cost_all, 4),
            "saving_vs_prop_vs_direct": round(
                statistics.mean(r["cost_prop"] for r in rows)
                / max(1, statistics.mean(r["cost_direct"] for r in rows)),
                2,
            ),
        }

    summary = {
        "manifest": {
            "run_id": run_id,
            "kind": "m1-propagation (offline, no model)",
            "corpus": str(corpus),
            "memory_entries": len(memory),
            "edges_used_by": edges,
            "nodes_with_downstream": nodes_with_out,
            "trials": args.trials,
            "seed": args.seed,
            "budget": args.budget,
            "note": "传播精度离线不可测，仅测成本结构",
        },
        "by_k": table,
        "ledger_summary": ledger.summary(),
        "replay_status_sample": dict(list(ledger.replay().items())[:5]),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")

    print(f"memory={len(memory)} edges={edges} nodes_with_downstream={nodes_with_out}")
    print(f"cost_all(full invalidation) = {cost_all} tokens")
    print(f"\n{'k':>2} {'suspect(mean)':>14} {'prop_cost':>10} {'saving':>8} {'prop/direct':>12}")
    for k, v in table.items():
        print(
            f"{k:>2} {v['suspect_mean']:>14} {v['cost_prop_mean']:>10} "
            f"{v['saving_vs_full']:>7.1%} {v['saving_vs_prop_vs_direct']:>11}x"
        )
    print(f"\nrun dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
