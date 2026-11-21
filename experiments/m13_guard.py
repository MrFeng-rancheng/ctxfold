# -*- coding: utf-8 -*-
"""M13：去掉校验（守卫）的消融——改对了的口径。

同一条 60 轮序列，第 25 轮改掉序列接下来最常问的 3 个符号。
  有校验：不改记忆里的指纹 -> 装配器发现符号变了 -> 判失效、重读
  无校验：每轮开头把记忆指纹刷成当前世界的值 -> 装配器永远看不出前提变了
度量：总 token、校验触发次数、免算轮数、以及「静默复用陈旧结论」的轮数（只有无校验版会大于 0）。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.tasks import build_tasks  # noqa: E402
from ctxfold.tokenize import token_count  # noqa: E402

STDLIB = Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")
TURNS, MUTATE_AT, BUDGET = 60, 25, 1600


def run_variant(no_guard: bool):
    chunks, index, sha = load_corpus(STDLIB / "http")
    by = {c.cid: c for c in chunks}
    tasks = build_tasks(chunks, TURNS, 7, locality=True, far_ref=0.4)

    # 改掉「第 25 轮之后最常被问到」的 3 个符号，保证失效真的会发生
    hot = [cid for cid, _ in Counter(t["cid"] for t in tasks[MUTATE_AT:]).most_common(3)]
    memory: dict = {}
    history: list[str] = []
    changed: set[str] = set()
    rows = []
    for t, task in enumerate(tasks, 1):
        if t == MUTATE_AT:
            for cid in hot:
                by[cid].text = by[cid].text + "\n    # mutated\n    return None"
                by[cid].tokens = token_count(by[cid].text)
                changed.add(cid)
        if no_guard:
            for cid, mem in memory.items():
                ck = by.get(cid)
                if ck is not None:
                    mem.file_sha = ck.file_sha
                    mem.chunk_sha = ck.text_sha
        res = assemble("ours", task["query"], history, by, index, memory, sha, budget=BUDGET)
        history.append(res.history_append)
        dec = " ".join(getattr(res, "decisions", []) or [])
        stale_now = 0
        for part in dec.split():
            if part.startswith("stale_now="):
                stale_now = int(part.split("=")[1])
        rows.append({
            "t": t,
            "tokens": token_count(res.prompt),
            "no_model": bool(res.no_model_needed),
            "stale_now": stale_now,
            "hit_mutated": task["cid"] in changed,
        })
    post = [r for r in rows if r["t"] >= MUTATE_AT]
    return {
        "variant": "无校验" if no_guard else "有校验",
        "tokens_total": sum(r["tokens"] for r in rows),
        "tokens_per_turn": round(st.mean(r["tokens"] for r in rows), 1),
        "no_model_turns": sum(1 for r in rows if r["no_model"]),
        "stale_hits": sum(r["stale_now"] for r in rows),
        "silent_stale_turns": sum(1 for r in post if r["hit_mutated"] and r["no_model"]),
        "mutated": sorted(changed),
    }


def main() -> int:
    a, b = run_variant(no_guard=False), run_variant(no_guard=True)
    out = {"manifest": {"corpus": str(STDLIB / "http"), "turns": TURNS,
                        "mutate_at": MUTATE_AT, "budget": BUDGET,
                        "mutated": a["mutated"]}, "rows": [a, b]}
    path = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m13")
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")

    lines = ["# m13 去掉校验的消融（自动生成，勿手改）", "",
             f"60 轮，第 {MUTATE_AT} 轮改掉之后最常被问的 3 个符号，预算 {BUDGET}。", "",
             "| 版本 | 总 token | 每轮 token | 校验触发次数 | 免算轮数 | 静默复用陈旧结论的轮数 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in (a, b):
        lines.append("| %s | %s | %s | %d | %d | %d/%d |" %
                     (r["variant"], format(r["tokens_total"], ","), r["tokens_per_turn"],
                      r["stale_hits"], r["no_model_turns"], r["silent_stale_turns"],
                      len([1 for _ in range(TURNS - MUTATE_AT + 1)])))
    (ROOT / "experiments" / "RESULTS-m13.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("mutated:", a["mutated"])
    print("run dir:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
