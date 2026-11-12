"""M1 世界指纹实验：guard 粒度对"误失效"的影响（纯离线，不调用模型）。

问题：一条结论固化时，guard 应该绑"整个文件"还是"这个符号"？
      文件级 guard 实现极简，但一个无关的函数被改，整文件结论全废（误失效）；
      符号级 guard 更精确，但要求 cid 与符号稳定对应。

做法：
  1) 把语料复制到临时仓库，跑 N 轮建立记忆；
  2) 在 k 个符号上做"真实修改"（插入一行注释，保持 AST 合法）；
  3) 分别按 file / symbol 两种粒度计算失效集合，统计误失效率与重算成本。

指标：
  modified        真实被改的符号数
  stale(symbol)   符号级判定失效的条数（应 ≈ modified）
  stale(file)     文件级判定失效的条数
  false_positive  stale(file) - stale(symbol)
  fp_rate         false_positive / 记忆总数
  recomp_tokens   需要重新读原文的 token 量（失效条目原文 token 之和）
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import build_symbol_index, chunk_repo, load_corpus, resolve_dependencies  # noqa: E402
from ctxfold.tokenize import TOKENIZER_NAME, token_count  # noqa: E402

DEFAULT_CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)


def warmup(memory, chunks_by_cid, index, tasks, current_sha, budget):
    """跑若干轮，把结论固化进 memory。"""
    history = []
    for task in tasks:
        assemble(
            method="ours",
            query=task["query"],
            history=history,
            chunks_by_cid=chunks_by_cid,
            index=index,
            memory=memory,
            current_sha=current_sha,
            budget=budget,
        )


def mutate(repo: Path, targets, rng) -> list[str]:
    """在目标 chunk 的函数体里插一行注释：AST 仍合法，但文本变了。"""
    changed = []
    for ck in targets:
        f = repo / ck.path
        lines = f.read_text(encoding="utf-8").splitlines()
        idx = ck.start  # 插在 def 那一行之后（1-based -> 索引 = start）
        if idx >= len(lines):
            continue
        indent = " " * (len(lines[ck.start]) - len(lines[ck.start].lstrip()) + 4)
        lines.insert(idx, f"{indent}# mutated-{rng.randrange(10**6):06d}")
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        changed.append(ck.cid)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--mutate", type=int, default=3, help="被真实修改的符号数")
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    src = Path(args.corpus)
    if not src.exists():
        print(f"[FATAL] corpus not found: {src}")
        return 2

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-m1-fingerprint"
    out = ROOT / "experiments" / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    repo = out / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    shutil.copytree(src, repo)

    # 1) 原始状态：建记忆
    chunks, index, sha = load_corpus(repo)
    by_cid = {c.cid: c for c in chunks}

    pool = [c for c in chunks if c.tokens >= 40]
    rng.shuffle(pool)
    tasks = [
        {"query": f"{c.name} 是怎么工作的？它调用的东西是什么？"} for c in pool[: args.turns]
    ]
    memory: dict[str, Memory] = {}
    warmup(memory, by_cid, index, tasks, sha, args.budget)
    n_mem = len(memory)
    print(f"warmup: memory={n_mem} entries from {len(tasks)} turns")

    # 2) 真实修改 k 个符号（优先散落在不同文件）
    mem_chunks = [by_cid[cid] for cid in memory]
    by_file: dict[str, list] = {}
    for c in mem_chunks:
        by_file.setdefault(c.path, []).append(c)
    picked_files = rng.sample(sorted(by_file), min(args.mutate, len(by_file)))
    targets = [rng.choice(by_file[f]) for f in picked_files]
    changed = mutate(repo, targets, rng)
    print(f"mutated {len(changed)} symbols in {len(set(t.path for t in targets))} files")

    # 3) 重新切块（模拟"世界变了"）
    chunks2 = chunk_repo(repo)
    by_cid2 = {c.cid: c for c in chunks2}
    sha2 = {c.path: c.file_sha for c in chunks2}

    # 4) 两种粒度下的失效判定
    res = {}
    for level in ("file", "symbol"):
        stale, recomp = [], 0
        for cid, mem in memory.items():
            ck = by_cid2.get(cid)
            if ck is None:
                stale.append(cid)
                recomp += by_cid[cid].tokens
            elif level == "file":
                if sha2.get(ck.path) != mem.file_sha:
                    stale.append(cid)
                    recomp += ck.tokens
            else:
                if mem.chunk_sha and ck.text_sha != mem.chunk_sha:
                    stale.append(cid)
                    recomp += ck.tokens
        res[level] = {"stale": len(stale), "recomp_tokens": recomp, "cids": sorted(stale)}

    fp = res["file"]["stale"] - res["symbol"]["stale"]
    summary = {
        "manifest": {
            "run_id": run_id,
            "kind": "m1-fingerprint (offline, no model)",
            "corpus": str(src),
            "turns": args.turns,
            "memory_entries": n_mem,
            "mutated_symbols": len(changed),
            "mutated_files": len(set(t.path for t in targets)),
            "tokenizer": TOKENIZER_NAME,
            "budget": args.budget,
            "seed": args.seed,
        },
        "file_guard": res["file"],
        "symbol_guard": res["symbol"],
        "false_positive": fp,
        "fp_rate_of_memory": round(fp / n_mem, 4) if n_mem else None,
        "recomp_tokens_ratio_file_vs_symbol": round(
            res["file"]["recomp_tokens"] / max(1, res["symbol"]["recomp_tokens"]), 2
        ),
        "changed": changed,
        "target_spans": [t.span for t in targets],
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )

    print(f"\n{'guard':8} {'stale':>6} {'recomp_tok':>11}")
    for level in ("file", "symbol"):
        print(f"{level:8} {res[level]['stale']:>6} {res[level]['recomp_tokens']:>11}")
    print(
        f"\nfalse_positive={fp} ({summary['fp_rate_of_memory']:.1%} of memory)  "
        f"recomp ratio file/symbol = {summary['recomp_tokens_ratio_file_vs_symbol']}x"
    )
    print(f"run dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
