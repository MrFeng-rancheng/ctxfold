# -*- coding: utf-8 -*-
"""m11：真实会话数据实验。

语料 = 真实仓库代码；任务 = 真实会话里用户的原话（未经改写），
gold = 原话中出现的符号名 + 这些符号的 1 跳依赖（机械生成，无人工判断）。
用法：python experiments/m11_real.py [--budget 1600] [--max-turns 200]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics as st
import sys
import zstandard as zstd
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.retrieve import BM25  # noqa: E402
import m2_baselines as m2  # noqa: E402

SESS = Path(r"C:\Users\13956\.dsh\sessions")
CORPUS = ROOT
METHODS = ["full", "window", "summary", "grepriag", "shortsym", "compress", "memgpt", "ours"]


def user_texts(path: Path) -> list[str]:
    """从 zstd 压缩会话流里抽出用户原话（按出现顺序）。"""
    out: list[str] = []
    d = zstd.ZstdDecompressor()
    try:
        with open(path, "rb") as fh:
            raw = d.stream_reader(fh).read().decode("utf-8", "replace")
    except Exception:
        return out

    def dig(o, depth=0):
        if depth > 8:
            return
        if isinstance(o, dict):
            role = o.get("role") or o.get("sender") or o.get("author")
            if isinstance(role, str) and role.lower() in ("user", "human"):
                for k in ("text", "content", "body", "message"):
                    v = o.get(k)
                    if isinstance(v, str) and len(v.strip()) >= 6:
                        out.append(v.strip())
                        return
                    if isinstance(v, list):
                        buf = []
                        for part in v:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                buf.append(part["text"])
                            elif isinstance(part, str):
                                buf.append(part)
                        if buf:
                            out.append("\n".join(buf).strip())
                            return
            for v in o.values():
                dig(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                dig(v, depth + 1)

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        dig(o)
    return out


def collect_queries() -> list[str]:
    qs: list[str] = []
    for dp, _dn, fn in os.walk(SESS):
        for f in fn:
            if f.endswith(".jsonl.zstd"):
                qs.extend(user_texts(Path(dp) / f))
    return qs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--min-cites", type=int, default=2)
    args = ap.parse_args()

    chunks, index, sha = load_corpus(CORPUS)
    by_cid = {c.cid: c for c in chunks}
    bm25 = BM25(chunks)
    names: dict[str, list[str]] = {}
    for c in chunks:
        short = c.name.split(".")[-1].split("::")[-1]
        if len(short) >= 4:
            names.setdefault(short, []).append(c.cid)

    raw_q = collect_queries()
    tasks, seen, skipped = [], set(), 0
    for text in raw_q:
        hits = sorted({n for n in names
                       if (re.search(r"\b%s\b" % re.escape(n), text)
                           or (len(n) >= 6 and n.lower() in text.lower()))})
        if not hits:
            skipped += 1
            continue
        cids = sorted({cid for n in hits for cid in names[n]})
        gold = set()
        for cid in cids:
            gold.add(cid)
            for dep in (index.deps.get(cid, []) if hasattr(index, "deps") else []):
                gold.add(dep)
        key = text[:120]
        if key in seen:
            continue
        seen.add(key)
        tasks.append({"cid": cids[0], "query": text[:600], "gold": sorted(gold), "far_ref": False})
        if len(tasks) >= args.max_turns:
            break

    print(f"chunks={len(chunks)} raw_user_msgs={len(raw_q)} no_cite={skipped} tasks={len(tasks)}")
    if len(tasks) < args.min_cites:
        print("[FATAL] 真实任务太少，无法成表")
        return 3

    res = {m: m2.run(m, tasks, by_cid, index, sha, bm25, args.budget) for m in METHODS}
    full_tokens = [r["tokens"] for r in res["full"]]
    total_full = sum(full_tokens)

    table = {}
    for m, rows in res.items():
        tok = sum(r["tokens"] for r in rows)
        table[m] = {
            "total_tokens": tok,
            "c_cum": round(1 - tok / total_full, 4),
            "r_prompt": round(st.mean(r["r_prompt"] for r in rows), 4),
            "r_avail": round(st.mean(r["r_avail"] for r in rows), 4),
            "no_model_needed": round(sum(r["no_model_needed"] for r in rows) / len(rows), 4),
            "tokens_per_turn": round(tok / len(rows), 1),
        }

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m11-real")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(
        {"manifest": {"corpus": str(CORPUS), "tasks": len(tasks), "budget": args.budget,
                      "source": "DSH 真实会话用户原话（未经改写）"},
         "table": table}, ensure_ascii=False, indent=2), "utf-8")

    lines = ["# m11 真实会话实验（自动生成）", "",
             f"任务数 {len(tasks)}，预算 {args.budget}，语料 `{CORPUS}`", "",
             "| 方法 | 总 token | 每轮 token | C_cum | 严格可见率 | 可召回率 |", "| --- | --- | --- | --- | --- | --- |"]
    for m in METHODS:
        v = table[m]
        lines.append(f"| {m} | {v['total_tokens']:,} | {v['tokens_per_turn']} | {v['c_cum']:.3f} | "
                     f"{v['r_prompt']:.3f} | {v['r_avail']:.3f} |")
    (ROOT / "experiments" / "RESULTS-m11.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n%-9s %10s %8s %8s %8s" % ("method", "total_tok", "C_cum", "R_prompt", "R_avail"))
    for m in METHODS:
        v = table[m]
        print("%-9s %10s %8.3f %8.3f %8.3f" % (m, format(v["total_tokens"], ","), v["c_cum"],
                                               v["r_prompt"], v["r_avail"]))
    print(f"\nrun dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
