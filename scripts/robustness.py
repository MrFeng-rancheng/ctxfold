"""robustness：拿一个大真实代码库喂给切块器/装配器，统计崩溃与跳过。

一个公开工具如果在真实代码上崩，其它优点都不作数。本脚本做三件事：
  1. 逐文件切块，记录成功/跳过（语法错、非 UTF-8）/异常（含异常类型）；
  2. 对切出来的 chunk 做一次装配演练，确认不会炸；
  3. 输出机器可读 summary，便于回归对比。

用法：
  python scripts/robustness.py --corpus <path> [--limit N]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import chunk_file, load_corpus  # noqa: E402
from ctxfold.tokenize import TOKENIZER_NAME  # noqa: E402

STDLIB = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(STDLIB))
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个文件（0=全部）")
    args = ap.parse_args()

    root = Path(args.corpus)
    if not root.exists():
        print(f"[FATAL] corpus not found: {root}")
        return 2

    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    if args.limit:
        files = files[: args.limit]
    print(f"corpus={root}  files={len(files)}  tokenizer={TOKENIZER_NAME}")

    t0 = time.perf_counter()
    ok = skipped = 0
    errors: Counter = Counter()
    skip_reasons: Counter = Counter()
    examples: dict[str, str] = {}
    all_chunks = []
    for p in files:
        try:
            got = chunk_file(p, root)
        except Exception as e:  # 任何异常都算失败，记录类型与首个样例
            name = type(e).__name__
            errors[name] += 1
            examples.setdefault(name, f"{p}: {e}")
            continue
        if got:
            ok += 1
            all_chunks.extend(got)
        else:
            skipped += 1
            # 区分"语法错/编码错"与"合法但没有可切符号"——不能让丢弃原因不明
            import ast as _ast
            try:
                _ast.parse(p.read_bytes().decode("utf-8"))
                skip_reasons["legal_but_no_symbol"] += 1
            except UnicodeDecodeError:
                skip_reasons["not_utf8"] += 1
            except SyntaxError:
                skip_reasons["syntax_error"] += 1
            except Exception as e:
                skip_reasons[type(e).__name__] += 1
    elapsed = time.perf_counter() - t0

    # 装配演练：随机挑若干 chunk 当查询，确认不炸
    asm_errors = Counter()
    asm_ok = 0
    if all_chunks:
        by_cid = {c.cid: c for c in all_chunks}
        from ctxfold.chunker import build_symbol_index, collect_imports, module_file_map, resolve_dependencies

        index = build_symbol_index(all_chunks)
        resolve_dependencies(all_chunks, index,
                             imports=collect_imports(root), modmap=module_file_map(root))
        sha = {c.path: c.file_sha for c in all_chunks}
        memory: dict[str, Memory] = {}
        history: list[str] = []
        step = max(1, len(all_chunks) // 50)
        for c in all_chunks[::step][:50]:
            try:
                res = assemble("ours", f"{c.name} 是怎么工作的？", history,
                               by_cid, index, memory, sha, budget=1600)
                history.append(res.history_append)
                asm_ok += 1
            except Exception as e:
                asm_errors[type(e).__name__] += 1
                examples.setdefault("asm:" + type(e).__name__, f"{c.cid}: {e}")

    toks = [c.tokens for c in all_chunks]
    summary = {
        "manifest": {"corpus": str(root), "files": len(files), "tokenizer": TOKENIZER_NAME},
        "files_chunked": ok,
        "files_skipped_no_chunk": skipped,
        "skip_reasons": dict(skip_reasons),
        "chunker_errors": dict(errors),
        "assemble_runs": asm_ok,
        "assemble_errors": dict(asm_errors),
        "chunks": len(all_chunks),
        "tokens_median": int(st.median(toks)) if toks else 0,
        "tokens_max": max(toks) if toks else 0,
        "elapsed_s": round(elapsed, 2),
        "examples": examples,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:2000])

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-robustness")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nrun dir: {out}")
    return 0 if not errors and not asm_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
