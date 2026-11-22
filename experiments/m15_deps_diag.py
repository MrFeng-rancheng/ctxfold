# -*- coding: utf-8 -*-
"""M15 诊断：依赖题为什么掉分——装配出来的 prompt 里到底有没有"被调用名"。

离线、不调模型。复刻 m3_online 的题序（同一符号先问 q_exc、再 q_locate、最后 q_deps），
逐步统计：
  1) gold（该符号 1 跳依赖名）有多少个、有多少个真的出现在 prompt 文本里；
  2) 目标符号本身落在哪一层（raw / card / claim / placeholder）；
  3) 卡片的 `calls:` 是否被截断（旧实现截到 6 个）；
  4) 依赖项本身落在哪一层。
"""
from __future__ import annotations

import re
import statistics as st
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
import m3_online as m3  # noqa: E402

STDLIB = Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")


def names_in(prompt: str, names: set[str]) -> int:
    low = prompt.lower()
    return sum(1 for n in names if re.search(r"(?<![a-z0-9_])%s(?![a-z0-9_])" % re.escape(n.lower()), low))


def main() -> int:
    n_tasks = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    chunks, index, sha = load_corpus(STDLIB / "http")
    by = {c.cid: c for c in chunks}
    questions = m3.make_questions(by, chunks, n_tasks, 7)

    memory: dict = {}
    history: list[str] = []
    rows = []
    for task in questions:
        deps = [by[d].name for d in by[task["cid"]].__dict__.get("deps", []) if d in by]
        if not deps:
            continue
        for kind in ("q_exc", "q_locate"):
            res = assemble("ours", task[kind]["query"], history, by, index, memory, sha, budget=1600)
            history.append(res.history_append)
        res = assemble("ours", task["q_deps"]["query"], history, by, index, memory, sha, budget=1600)
        history.append(res.history_append)

        prompt = res.prompt
        got = names_in(prompt, set(deps))
        target_level = (
            "raw" if task["cid"] in res.included_cids else
            "claim" if task["cid"] in res.claim_cids else
            "card" if task["cid"] in res.card_cids else
            "placeholder" if task["cid"] in res.placeholder_cids else "none"
        )
        dep_cids = [d for d in by[task["cid"]].__dict__.get("deps", []) if d in by]
        dep_levels = Counter(
            "raw" if d in res.included_cids else
            "claim" if d in res.claim_cids else
            "card" if d in res.card_cids else
            "placeholder" if d in res.placeholder_cids else "none"
            for d in dep_cids
        )
        rows.append({"deps": len(deps), "in_prompt": got, "target_level": target_level,
                     "dep_levels": dep_levels, "tokens": len(prompt) / 3.5})

    print(f"题目数 {len(rows)}（http 语料，seed=7，预算 1600）")
    print()
    full = sum(1 for r in rows if r["in_prompt"] == r["deps"])
    zero = sum(1 for r in rows if r["in_prompt"] == 0)
    print("== 被调用名是否进了 prompt ==")
    print(f"  全部名字都在 prompt 里 : {full}/{len(rows)}  ({full/len(rows):.1%})")
    print(f"  一个名字都没进 prompt : {zero}/{len(rows)}  ({zero/len(rows):.1%})")
    print(f"  覆盖率中位            : {st.median([r['in_prompt']/r['deps'] for r in rows]):.3f}")
    print()
    print("== 目标符号的层级分布 ==")
    for lv, c in Counter(r["target_level"] for r in rows).most_common():
        print(f"  {lv:12s} {c:3d}")
    print()
    print("== 依赖项（被调用名所属符号）的层级分布 ==")
    tot = Counter()
    for r in rows:
        tot.update(r["dep_levels"])
    s = sum(tot.values())
    for lv, c in tot.most_common():
        print(f"  {lv:12s} {c:4d}  ({c/s:.1%})")
    print()
    print("== 截断风险 ==")
    many = [r for r in rows if r["deps"] > 6]
    print(f"  依赖数 > 6 的题目: {len(many)}/{len(rows)}  最大 {max(r['deps'] for r in rows)}")
    print(f"  单轮 prompt 估算 token 中位: {st.median([r['tokens'] for r in rows]):.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
