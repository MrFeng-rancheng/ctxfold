"""任务序列生成（实验用，可复现）。

三种模式可叠加：
  locality  时间局部性（0.7 概率落在最近 hot 轮用过的文件）
  far_ref   长程引用（把很久以前出现过的符号拉进本轮依赖，window 的死穴）
"""
from __future__ import annotations

import random


def build_tasks(chunks, n_turns: int, seed: int, locality: bool = False, hot: int = 8,
                far_ref: float = 0.0) -> list[dict]:
    rng = random.Random(seed)
    pool = [c for c in chunks if c.tokens >= 40]
    by_cid = {c.cid: c for c in chunks}
    by_file: dict[str, list] = {}
    for c in pool:
        by_file.setdefault(c.path, []).append(c)

    used: set[str] = set()
    recent: list[str] = []
    tasks: list[dict] = []
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

        deps = list(pick.__dict__.get("deps", []))
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
        if far_ref > 0 and len(tasks) >= 12 and rng.random() < far_ref:
            lo, hi = max(0, len(tasks) - 45), max(0, len(tasks) - 8)
            if hi > lo:
                old = tasks[rng.randrange(lo, hi)]
                if old["cid"] != pick.cid:
                    task["query"] = (
                        f"{pick.name} 是怎么和 {old['name']} 配合工作的？两者的实现分别是什么？"
                    )
                    task["gold"] = [pick.cid, old["cid"]] + deps
                    task["far_ref"] = True
        tasks.append(task)
        recent.append(pick.path)
        recent = recent[-hot:]
    return tasks


def digest(chunk) -> str:
    """抽取式摘要基线用的一行摘要：签名 + 位置。不含实现细节（有损）。"""
    first = chunk.text.strip().splitlines()[0].strip()
    return f"- {chunk.name} @ {chunk.path}:{chunk.start}-{chunk.end} — {first[:80]}"
