"""M7 消融实验（离线）：把机制一个个关掉，看每个部件各值多少。

五个配置（同一任务序列、同一预算）：
  base         全部开启
  -closure     只保留命中项，不沿依赖展开（≈纯符号检索）
  -placeholder 已固化的也重新给原文（≈无记忆，只剩上下文裁剪）
  -card        摘要卡退化为占位符（只给 id）
  -claim       结论层退化为摘要卡
  +full        全量历史（成本上界）
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.tasks import build_tasks  # noqa: E402
from ctxfold.tokenize import TOKENIZER_NAME, token_count  # noqa: E402

CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)

CONFIGS = [
    ("base", frozenset()),
    ("-closure", frozenset({"closure"})),
    ("-placeholder", frozenset({"placeholder"})),
    ("-card", frozenset({"card"})),
    ("-claim", frozenset({"claim"})),
    ("+full", frozenset({"__full__"})),
]


def run(config: frozenset, tasks, by_cid, index, sha, budget=1600):
    is_full = "__full__" in config
    memory: dict[str, Memory] = {}
    history: list[dict] = []          # [{text, raw}]
    total, nomodel = 0, 0
    rp, ra, far = [], [], []

    for task in tasks:
        gold = set(task["gold"])
        if is_full:
            texts = [h["text"] for h in history] + [by_cid[task["cid"]].text]
            prompt = "\n\n".join(texts) + f"\n\n[问题] {task['query']}"
            seen = set().union(*[h["raw"] for h in history]) if history else set()
            raw_avail = seen | {task["cid"]}
            avail = raw_avail
            append, append_raw = by_cid[task["cid"]].text, {task["cid"]}
        else:
            res = assemble("ours", task["query"], [h["text"] for h in history], by_cid,
                           index, memory, sha, budget=budget, ablate=config)
            prompt = res.prompt
            raw_avail = set(res.included_cids)
            avail = raw_avail | set(res.placeholder_cids)
            nomodel += int(res.no_model_needed)
            append, append_raw = res.history_append, raw_avail

        r = len(gold & raw_avail) / len(gold)
        rp.append(r)
        ra.append(len(gold & avail) / len(gold))
        if task["far_ref"]:
            far.append(r)
        total += token_count(prompt)
        history.append({"text": append, "raw": append_raw})

    return {
        "tokens": total,
        "r_prompt": st.mean(rp),
        "r_avail": st.mean(ra),
        "far_r_prompt": st.mean(far) if far else None,
        "no_model_rate": nomodel / len(tasks) if not is_full else 0.0,
    }


def main() -> int:
    chunks, index, sha = load_corpus(CORPUS)
    by_cid = {c.cid: c for c in chunks}
    tasks = build_tasks(chunks, 50, 7, locality=True, far_ref=0.4)
    print(f"chunks={len(chunks)} tasks={len(tasks)} tokenizer={TOKENIZER_NAME}")

    rows = {name: run(cfg, tasks, by_cid, index, sha) for name, cfg in CONFIGS}
    base_tokens = rows["base"]["tokens"]

    print(f"\n{'配置':14}{'总token':>10}{'相对base':>10}{'R_prompt':>10}{'R_avail':>9}{'长程R':>8}")
    for name, r in rows.items():
        rel = f"{r['tokens'] / base_tokens:.2f}x"
        far = f"{r['far_r_prompt']:.3f}" if r["far_r_prompt"] is not None else "-"
        print(f"{name:14}{r['tokens']:>10,}{rel:>10}{r['r_prompt']:>10.3f}"
              f"{r['r_avail']:>9.3f}{far:>8}")

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m7-ablation")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "manifest": {"corpus": str(CORPUS), "turns": len(tasks), "budget": 1600,
                     "tokenizer": TOKENIZER_NAME, "note": "ablation, single seed"},
        "table": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv)
                      for kk, vv in v.items()} for k, v in rows.items()},
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nrun dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
