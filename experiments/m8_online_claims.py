"""M8 在线 E（错误残留率）：让模型自己写"结论 + 可执行断言"，然后真的跑一遍。

这是 E 指标唯一诚实的测法：
  模型读代码 → 产出一条断言（python -c 一行） → 我们用 subprocess 执行 →
  returncode==0 记 pass，否则记 fail。E = fail / total。

它同时回答了本文的一条设计判据——"能被验证的才配被记住"：
如果模型写不出可执行断言，这条结论就不该进入状态。

用法：
  python experiments/m8_online_claims.py --tasks 12
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold import llm  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402

CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)

PROMPT = """阅读下面的代码片段。请写一条**可执行的 Python 断言**，验证它一个具体、可观察的行为。

要求：
1. 只输出一行 `python -c` 可执行的代码，不要 markdown、不要解释；
2. 代码里必须包含 `assert`；
3. 只能使用标准库与被测模块本身；
4. 若无法写出可执行断言，只输出 NO_VERIFIABLE。

模块路径提示：`{module_hint}`

代码片段（{path}:{start}-{end}）：
```python
{code}
```"""


def clean(code: str) -> str:
    code = (code or "").strip()
    code = re.sub(r"^```[a-zA-Z]*\n?", "", code)
    code = re.sub(r"\n?```$", "", code).strip()
    if code.startswith("python -c"):
        code = code[len("python -c"):].strip()
    # 只在整段被引号包裹时才去掉引号；不能用 strip，否则会吃掉代码末尾的引号
    for q in ('"', "'"):
        if len(code) > 1 and code.startswith(q) and code.endswith(q):
            code = code[1:-1]
            break
    return code


def run_assert(code: str, cwd: Path, py_path: Path, timeout: int = 20) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            [sys.executable, "-c", code], cwd=str(cwd), capture_output=True,
            text=True, encoding="utf-8", timeout=timeout,
            env={**__import__("os").environ, "PYTHONPATH": str(py_path)},
        )
        return p.returncode == 0, (p.stderr or "")[:300]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--tasks", type=int, default=12)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    root = Path(args.corpus)
    chunks, index, sha = load_corpus(root)
    pool = [c for c in chunks if c.tokens >= 60]
    random.Random(args.seed).shuffle(pool)
    sample = pool[: args.tasks]

    is_pkg = (root / "__init__.py").exists()
    py_path = root.parent if is_pkg else root   # 让 import pkg.mod 能解析
    rows = []
    for i, c in enumerate(sample, 1):
        rel = c.path[:-3].replace("/", ".")
        mod = f"{root.name}.{rel}" if is_pkg else rel
        attr = c.name.split(".")[-1].split("#")[0]
        hint = f"from {mod.rsplit(chr(46), 1)[0]} import {attr}"
        msg = PROMPT.format(module_hint=hint, path=c.path, start=c.start, end=c.end, code=c.text[:2500])
        try:
            resp = llm.chat([{"role": "user", "content": msg}], max_tokens=800)
            out = resp["choices"][0]["message"].get("content") or ""
            truncated = resp["choices"][0].get("finish_reason") == "length"
            usage = resp.get("usage", {}) or {}
        except RuntimeError as e:
            # 基础设施失败（DNS/超时/限流）不是"模型写错了"，绝不能计入 E
            rows.append({"cid": c.cid, "kind": "infra_error", "ok": None, "error": str(e)})
            print(f"  [infra] {c.name}: {str(e)[:80]}")
            continue

        code = clean(out)
        if truncated:
            rows.append({"cid": c.cid, "kind": "truncated", "ok": None,
                         "code": code[:200], "usage": usage.get("total_tokens", 0)})
            continue
        if code.upper().startswith("NO_VERIFIABLE") or "assert" not in code:
            rows.append({"cid": c.cid, "kind": "no_verifiable", "ok": False,
                         "code": code[:200], "usage": usage.get("total_tokens", 0)})
        else:
            ok, err = run_assert(code, root, py_path)
            rows.append({"cid": c.cid, "kind": "assert", "ok": ok, "code": code[:400],
                         "err": err, "usage": usage.get("total_tokens", 0)})
        print(f"  [{i}/{len(sample)}] {c.name:<40} {'pass' if rows[-1]['ok'] else 'FAIL'}")

    scored = [r for r in rows if r.get("ok") is not None]   # 剔除 infra_error
    n = len(scored)
    fails = sum(1 for r in scored if not r["ok"])
    E = fails / n if n else None
    summary = {
        "manifest": {"mode": "online-E", "base": llm.config()["base"], "model": llm.config()["model"],
                     "corpus": str(root), "tasks": n, "seed": args.seed},
        "E": round(E, 4) if E is not None else None,
        "pass": n - fails, "fail": fails,
        "infra_errors": sum(1 for r in rows if r.get("kind") == "infra_error"),
        "truncated": sum(1 for r in rows if r.get("kind") == "truncated"),
        "scored": n,
        "no_verifiable": sum(1 for r in rows if r.get("kind") == "no_verifiable"),
        "usage_total": sum(r.get("usage", 0) for r in rows),
    }
    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m8-online-E")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    with (out / "rows.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"run dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
