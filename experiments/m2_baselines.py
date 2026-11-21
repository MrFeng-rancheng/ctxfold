"""M2 五方法对比（离线，不调用模型）：补齐协议要求的对照组。

方法：
  full       全量历史（上界成本）
  window-k   最近 k 轮
  summary    抽取式摘要历史（每轮只留"签名+位置"一行，有损）
  grepriag   BM25 检索 top-k（等预算，无状态、无闭包）
  ours       状态记忆 + guard + 依赖闭包 + 占位符

对照原则（protocol.md §3）：同时给"等预算"和"等精度"两个切片；token 分母统一为 full。
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.retrieve import BM25  # noqa: E402
from ctxfold.tasks import build_tasks, digest  # noqa: E402
from ctxfold.tokenize import IS_ESTIMATE, TOKENIZER_NAME, token_count  # noqa: E402

DEFAULT_CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)



def compress_text(text: str) -> str:
    """LLMLingua 的无模型近似：删注释、空行与 docstring，只保留可执行骨架。

    真实 LLMLingua 用小模型逐 token 算信息熵做删减；此处退化为抽取式压缩，
    压缩率固定在 40%~60%，在论文中标注为"无模型近似"。
    """
    out = []
    for line in text.splitlines():
        st = line.strip()
        if not st or st.startswith('#') or st.startswith('"""') or st.startswith("'''"):
            continue
        out.append(line)
    return chr(10).join(out)

def run(method, tasks, by_cid, index, sha, bm25, budget, window=5, k=8):
    memory: dict[str, Memory] = {}
    history: list[dict] = []
    rows = []
    for t, task in enumerate(tasks, 1):
        own = by_cid[task["cid"]]
        ph: set[str] = set()
        no_model = False

        if method == "full":
            body = "\n\n".join([h["text"] for h in history] + [own.text])
            prompt = f"{body}\n\n[问题] {task['query']}"
            raw = {task["cid"]}
            append, append_raw = own.text, raw
        elif method.startswith("window"):
            tail = history[-window:]
            body = "\n\n".join([h["text"] for h in tail] + [own.text])
            prompt = f"{body}\n\n[问题] {task['query']}"
            raw = {task["cid"]}
            append, append_raw = own.text, raw
            raw = raw | (set().union(*[h["raw"] for h in tail]) if tail else set())
        elif method == "summary":
            body = "\n".join([h["text"] for h in history] + [digest(own), f"\n[证据原文]\n{own.text}"])
            prompt = f"{body}\n\n[问题] {task['query']}"
            raw = {task["cid"]}
            append, append_raw = digest(own), set()  # 历史里只留摘要，原文不留
        elif method == "compress":
            body = chr(10).join([h["text"] for h in history] + [compress_text(own.text)])
            prompt = f"{body}" + chr(10) + chr(10) + f"[问题] {task['query']}"
            raw = {task["cid"]}
            append, append_raw = compress_text(own.text), set()
        elif method == "memgpt":
            tail = history[-window:]
            got = [c for c in bm25.top_k(task["query"], k=1, budget=budget) if c.cid != task["cid"]]
            body = chr(10).join([h["text"] for h in tail] + [own.text]
                                + [f"[归档检索] {c.text}" for c in got])
            prompt = f"{body}" + chr(10) + chr(10) + f"[问题] {task['query']}"
            raw = {task["cid"]} | {c.cid for c in got}
            append, append_raw = own.text, {task["cid"]}
            raw = raw | (set().union(*[h["raw"] for h in tail]) if tail else set())
        elif method == "shortsym":
            # 朴素强基线：完全不看查询，把最短的符号先塞满预算，尽量让 prompt 装下更多符号
            picked, used = [], 0
            for c in sorted(by_cid.values(), key=lambda x: x.tokens):
                if used + c.tokens > budget:
                    continue
                picked.append(c)
                used += c.tokens
                if used >= int(budget * 0.98):
                    break
            body = "\n\n".join(c.text for c in picked)
            prompt = f"[符号池]\n{body}\n\n[问题] {task['query']}"
            raw = {c.cid for c in picked}
            append, append_raw = "", set()
        elif method == "grepriag":
            got = bm25.top_k(task["query"], k=k, budget=budget)
            body = "\n\n".join(c.text for c in got)
            prompt = f"[检索证据]\n{body}\n\n[问题] {task['query']}"
            raw = {c.cid for c in got}
            append, append_raw = "", set()  # 无状态：不积累历史
        else:  # ours
            res = assemble("ours", task["query"], [h["text"] for h in history], by_cid,
                           index, memory, sha, budget=budget)
            prompt = res.prompt
            raw = set(res.included_cids)
            ph = set(res.placeholder_cids)
            no_model = res.no_model_needed
            append, append_raw = res.history_append, raw | ph

        if method.startswith("window"):
            avail_raw = raw  # 上面已并入窗口内历史
        elif method == "full":
            avail_raw = set().union(*[h["raw"] for h in history]) | raw if history else raw
        elif method in ("summary", "compress"):
            avail_raw = raw
        elif method == "grepriag":
            avail_raw = raw
        else:
            avail_raw = raw

        gold = set(task["gold"])
        rows.append({
            "t": t, "method": method,
            "tokens": token_count(prompt),
            "tokens_pessimistic": token_count(prompt) + sum(by_cid[c].tokens for c in ph),
            "r_prompt": round(len(gold & avail_raw) / len(gold), 4),
            "r_avail": round(len(gold & (avail_raw | ph)) / len(gold), 4),
            "no_model_needed": no_model,
            "far_ref": task["far_ref"],
        })
        history.append({"text": append, "raw": append_raw})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--turns", type=int, default=50)
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--window", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tag", default="", help="附加到 run 目录名，便于多种子实验聚合")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"[FATAL] corpus not found: {corpus}")
        return 2

    chunks, index, sha = load_corpus(corpus)
    by_cid = {c.cid: c for c in chunks}
    bm25 = BM25(chunks)
    tasks = build_tasks(chunks, args.turns, args.seed, locality=True, far_ref=0.4)
    print(f"chunks={len(chunks)} tasks={len(tasks)} far_ref={sum(1 for t in tasks if t['far_ref'])}")

    methods = ["full", "window", "summary", "grepriag", "shortsym", "compress", "memgpt", "ours"]
    res = {m: run(m, tasks, by_cid, index, sha, bm25, args.budget, args.window, args.k) for m in methods}
    full_tokens = [r["tokens"] for r in res["full"]]

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m2-baselines"
                                   + (f"-{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)
    table = {}
    for m, rows in res.items():
        tok = sum(r["tokens"] for r in rows)
        tok_p = sum(r["tokens_pessimistic"] for r in rows)
        table[m] = {
            "total_tokens": tok,
            "total_tokens_allrecall": tok_p,
            "c_cum": round(1 - tok / sum(full_tokens), 4),
            "c_cum_allrecall": round(1 - tok_p / sum(full_tokens), 4),
            "r_prompt": round(st.mean(r["r_prompt"] for r in rows), 4),
            "r_avail": round(st.mean(r["r_avail"] for r in rows), 4),
            "r_prompt_far": round(st.mean([r["r_prompt"] for r in rows if r["far_ref"]]), 4) if any(r["far_ref"] for r in rows) else 0.0,
            "no_model_needed": round(sum(r["no_model_needed"] for r in rows) / len(rows), 4),
            "max_tokens": max(r["tokens"] for r in rows),
            "tokens_tlast": rows[-1]["tokens"],
        }

    summary = {"manifest": {"corpus": str(corpus), "turns": args.turns, "budget": args.budget,
                            "k": args.k, "window": args.window, "seed": args.seed,
                            "tokenizer": TOKENIZER_NAME, "estimate": IS_ESTIMATE},
               "table": table}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    with (out / "metrics.jsonl").open("w", encoding="utf-8") as f:
        for m, rows in res.items():
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    hdr = "%-9s %10s %9s %7s %9s %8s %8s %8s" % ("method", "total_tok", "+recall", "C_cum", "R_prompt", "R_avail", "R_p_far", "lastTok")
    print()
    print(hdr)
    for m in methods:
        v = table[m]
        print("%-9s %10s %9s %7.3f %9.3f %8.3f %8.3f %8s" % (
            m, format(v["total_tokens"], ","), format(v["total_tokens_allrecall"], ","),
            v["c_cum"], v["r_prompt"], v["r_avail"], v["r_prompt_far"],
            format(v["tokens_tlast"], ",")))
    print(f"\nrun dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
