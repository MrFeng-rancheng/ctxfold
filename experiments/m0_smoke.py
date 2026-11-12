"""M0 冒烟实验：纯离线，不调用任何模型。

目的：在本机真实代码库上，跑一遍"50 轮会话"，比较三种上下文策略的
      token 成本（C）与证据保留（R_prompt 严格 / R_avail 宽松），
      以及"本轮是否需要读原文"的比例（K，作为 H 免算率的离线代理）。

诚实声明：
  * 任务序列是合成的（随机抽符号提问），gold 由 AST 依赖近似得出。
  * 本实验只用于验证管线与量级，**不作为论文数据**。论文数据须走协议的 dev/test 划分与人工 gold。
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import build_symbol_index, chunk_repo, load_corpus, resolve_dependencies  # noqa: E402
from ctxfold.tokenize import IS_ESTIMATE, TOKENIZER_NAME, token_count  # noqa: E402

DEFAULT_CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)


def build_tasks(
    chunks, n_turns: int, seed: int, locality: bool = False, hot: int = 8, far_ref: float = 0.0
):
    """生成任务序列。

    locality=False：随机抽符号（M0 初版，对 window 过宽容）
    locality=True ：以 0.7 概率落在"最近 hot 轮用过的文件"上——模拟真实会话的时间局部性
    """
    rng = random.Random(seed)
    pool = [c for c in chunks if c.tokens >= 40]  # 太短的片段没有"证据"意义
    by_cid = {c.cid: c for c in chunks}
    by_file: dict[str, list] = {}
    for c in pool:
        by_file.setdefault(c.path, []).append(c)

    used: set[str] = set()
    recent: list[str] = []
    tasks = []
    guard = 0
    while len(tasks) < n_turns and guard < n_turns * 100:
        guard += 1
        pick = None
        if locality and recent and rng.random() < 0.7:
            f = rng.choice(recent)
            cand = [c for c in by_file.get(f, []) if c.cid not in used]
            if cand:
                pick = rng.choice(cand)
        if pick is None:
            cand = [c for c in pool if c.cid not in used]
            if not cand:
                break
            pick = rng.choice(cand)
        used.add(pick.cid)

        deps = [d for d in pick.__dict__.get("deps", [])]
        cross = any(by_cid[d].path != pick.path for d in deps)

        task = {
            "cid": pick.cid,
            "name": pick.name,
            "query": f"{pick.name} 具体是怎么工作的？它的实现和它调用的东西是什么？",
            "gold": [pick.cid] + deps,
            "file": pick.path,
            "cross_file": cross,
            "far_ref": False,
        }
        # 长程引用：把"很久以前出现过的符号"拉进本轮依赖里。
        # 这是 window 的真实死穴——局部性帮不了它，只有持久状态能。
        if far_ref > 0 and len(tasks) >= 12 and rng.random() < far_ref:
            lo = max(0, len(tasks) - 45)
            hi = max(0, len(tasks) - 8)
            if hi > lo:
                old = tasks[rng.randrange(lo, hi)]
                if old["cid"] != pick.cid:
                    task["query"] = (
                        f"{pick.name} 是怎么和 {old['name']} 配合工作的？"
                        f"两者的实现分别是什么？"
                    )
                    task["gold"] = [pick.cid, old["cid"]] + deps
                    task["far_ref"] = True
        tasks.append(task)
        recent.append(pick.path)
        recent = recent[-hot:]
    return tasks


def run_session(method, tasks, chunks_by_cid, index, current_sha, window=5, budget=1600, hops=1):
    memory: dict[str, Memory] = {}
    history: list[dict] = []
    rows = []
    for t, task in enumerate(tasks, 1):
        own = chunks_by_cid[task["cid"]]
        if method in ("full", "window"):
            # 朴素策略：只按问题检索到本符号的原文，然后把原文堆进历史
            evidence = own.text
            tail = history if method == "full" else history[-window:]
            body = "\n\n".join([h["text"] for h in tail] + [evidence])
            prompt = f"{body}\n\n[问题] {task['query']}"
            res_ids = [task["cid"]]
            ph_now: set[str] = set()
            no_model = False
            decisions = [f"{method}:evidence=1"]
            append = evidence
        else:
            res = assemble(
                method="ours",
                query=task["query"],
                history=[h["text"] for h in history],
                chunks_by_cid=chunks_by_cid,
                index=index,
                memory=memory,
                current_sha=current_sha,
                window=window,
                budget=budget,
                hops=hops,
            )
            prompt = res.prompt
            res_ids = res.included_cids
            ph_now = set(res.placeholder_cids)
            no_model = res.no_model_needed
            decisions = res.decisions
            append = res.history_append

        raw_now = set(res_ids)

        # 本轮原文可见集合（严格=在 prompt 里；宽松=在 prompt 或可 recall）
        if method == "full":
            seen = set().union(*[h["raw"] for h in history]) if history else set()
            raw_avail, any_avail = seen | raw_now, seen | raw_now
        elif method == "window":
            tail = history[-window:]
            seen = set().union(*[h["raw"] for h in tail]) if tail else set()
            raw_avail, any_avail = seen | raw_now, seen | raw_now
        else:
            raw_avail, any_avail = raw_now, raw_now | ph_now

        gold = set(task["gold"])
        r_prompt = len(gold & raw_avail) / len(gold)
        r_avail = len(gold & any_avail) / len(gold)
        tok = token_count(prompt)
        # 悲观估计：把本轮所有占位符都 recall 回来（ours 专属）
        tok_pess = tok + sum(chunks_by_cid[c].tokens for c in ph_now)

        rows.append(
            {
                "t": t,
                "method": method,
                "cross_file": bool(task.get("cross_file")),
                "far_ref": bool(task.get("far_ref")),
                "file": task.get("file"),
                "tokens": tok,
                "tokens_pessimistic": tok_pess,
                "chars": len(prompt),
                "r_prompt": round(r_prompt, 4),
                "r_avail": round(r_avail, 4),
                "no_model_needed": bool(no_model),
                "gold": sorted(task["gold"]),
                "raw_cids": sorted(res_ids),
                "ph_cids": sorted(ph_now),
                "decisions": decisions,
            }
        )
        history.append({"text": append, "raw": raw_now | ph_now})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--turns", type=int, default=50)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--locality", action="store_true", help="启用时间局部性任务序列")
    ap.add_argument("--hops", type=int, default=1)
    ap.add_argument("--far-ref", type=float, default=0.0, help="长程引用任务比例")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"[FATAL] corpus not found: {corpus}")
        return 2

    t0 = time.time()
    chunks = chunk_repo(corpus)
    index = build_symbol_index(chunks)
    resolve_dependencies(chunks, index)
    chunks_by_cid = {c.cid: c for c in chunks}
    current_sha = {c.path: c.file_sha for c in chunks}
    tasks = build_tasks(chunks, args.turns, args.seed, locality=args.locality, far_ref=args.far_ref)
    n_cross = sum(1 for t in tasks if t["cross_file"])
    n_far = sum(1 for t in tasks if t["far_ref"])
    print(
        f"corpus={corpus.name} chunks={len(chunks)} symbols={len(index)} "
        f"tasks={len(tasks)} cross_file={n_cross} far_ref={n_far} locality={args.locality}"
    )

    results = {}
    for method in ("full", "window", "ours"):
        results[method] = run_session(
            method, tasks, chunks_by_cid, index, current_sha, args.window, args.budget, args.hops
        )

    full_tokens = [r["tokens"] for r in results["full"]]
    summary = {"manifest": {}, "per_method": {}}

    for method, rows in results.items():
        cum = 0.0
        for r in rows:
            base = full_tokens[r["t"] - 1]
            r["c"] = round(1 - r["tokens"] / base, 4) if base else 0.0
            cum += r["c"]
        tok = sum(r["tokens"] for r in rows)
        tok_p = sum(r["tokens_pessimistic"] for r in rows)
        cross = [r for r in rows if r["cross_file"]]
        far = [r for r in rows if r["far_ref"]]
        same = [r for r in rows if not r["cross_file"]]
        summary["per_method"][method] = {
            "total_tokens": tok,
            "total_tokens_pessimistic": tok_p,
            "c_cum": round(1 - tok / sum(full_tokens), 4),
            "c_cum_pessimistic": round(1 - tok_p / sum(full_tokens), 4),
            "c_mean": round(cum / len(rows), 4),
            "r_prompt_mean": round(statistics.mean(r["r_prompt"] for r in rows), 4),
            "r_avail_mean": round(statistics.mean(r["r_avail"] for r in rows), 4),
            "r_prompt_cross_file": round(statistics.mean(r["r_prompt"] for r in cross), 4)
            if cross
            else None,
            "r_prompt_same_file": round(statistics.mean(r["r_prompt"] for r in same), 4)
            if same
            else None,
            "n_cross_file": len(cross),
            "r_prompt_far_ref": round(statistics.mean(r["r_prompt"] for r in far), 4)
            if far
            else None,
            "r_avail_far_ref": round(statistics.mean(r["r_avail"] for r in far), 4)
            if far
            else None,
            "n_far_ref": len(far),
            "no_model_needed_rate": round(
                sum(1 for r in rows if r["no_model_needed"]) / len(rows), 4
            ),
            "max_prompt_tokens": max(r["tokens"] for r in rows),
            "tokens_t1": rows[0]["tokens"],
            "tokens_tlast": rows[-1]["tokens"],
            "c_tlast": rows[-1]["c"],
        }

    run_id = (
        datetime.now().strftime("%Y%m%d-%H%M%S")
        + f"-m0-{corpus.name}"
        + ("-loc" if args.locality else "-rnd")
        + (f"-{args.tag}" if args.tag else "")
    )
    out = ROOT / "experiments" / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "kind": "m0-smoke (synthetic tasks, NOT paper data)",
        "corpus": str(corpus),
        "chunks": len(chunks),
        "turns": len(tasks),
        "seed": args.seed,
        "window": args.window,
        "budget": args.budget,
        "locality": args.locality,
        "n_cross_file_tasks": n_cross,
        "n_far_ref_tasks": n_far,
        "far_ref_rate": args.far_ref,
        "tokenizer": TOKENIZER_NAME,
        "tokenizer_is_estimate": IS_ESTIMATE,
        "elapsed_s": round(time.time() - t0, 2),
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    summary["manifest"] = manifest
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    with (out / "metrics.jsonl").open("w", encoding="utf-8") as f:
        for method, rows in results.items():
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")

    print(f"\n{'method':8} {'tokens':>9} {'C_cum':>7} {'R_prompt':>9} {'R_avail':>8} {'K':>6} {'maxTok':>7}")
    for method, s in summary["per_method"].items():
        print(
            f"{method:8} {s['total_tokens']:>9} {s['c_cum']:>7.3f} {s['r_prompt_mean']:>9.3f} "
            f"{s['r_avail_mean']:>8.3f} {s['no_model_needed_rate']:>6.3f} {s['max_prompt_tokens']:>7}"
        )
    print(f"\nrun dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
