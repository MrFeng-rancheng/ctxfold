"""校准：字符估算器（chars/3.5）与真实 tokenizer（cl100k_base）差多少，影响哪些结论。

三个问题：
  1. 在代码文本上，估算器的相对误差分布如何？
  2. 对**绝对 token 数**的影响有多大？
  3. 对**比值类指标（C_cum、R）** 的影响有多大？（理论上应很小，因为同一 tokenizer 同比例缩放）

需要 tiktoken：pip install tiktoken
用法：python scripts/calibrate_tokenizer.py
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.tasks import build_tasks  # noqa: E402

CPS = 3.5  # 估算器常数


def est(text: str) -> int:
    return 0 if not text else max(1, round(len(text) / CPS))


def main() -> int:
    try:
        import tiktoken
    except ImportError:
        print("需要 tiktoken：pip install tiktoken")
        return 2
    enc = tiktoken.get_encoding("cl100k_base")
    real = lambda t: len(enc.encode(t, disallowed_special=()))  # noqa: E731

    corpora = [
        ("Lib/http", Path(r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http")),
        ("ctxfold/src", ROOT / "src"),
    ]
    out = {}
    for name, root in corpora:
        if not root.exists():
            continue
        chunks, index, sha = load_corpus(root)
        errs = []
        for c in chunks:
            r = real(c.text)
            if r >= 20:  # 太短的片段误差没意义
                errs.append((est(c.text) - r) / r)
        if not errs:
            continue
        errs.sort()
        out[name] = {
            "chunks": len(errs),
            "median_err": round(st.median(errs), 4),
            "mean_err": round(st.mean(errs), 4),
            "p10": round(errs[int(0.1 * (len(errs) - 1))], 4),
            "p90": round(errs[int(0.9 * (len(errs) - 1))], 4),
            "abs_median": round(abs(st.median(errs)), 4),
        }
        print(f"{name:12} n={out[name]['chunks']:<4} 估算相对真实: "
              f"中位 {out[name]['median_err']:+.1%}  p10 {out[name]['p10']:+.1%}  "
              f"p90 {out[name]['p90']:+.1%}")

    # 对 C_cum 的影响：同一批 prompt 分别用两种 tokenizer 计总 token
    name, root = corpora[0]
    chunks, index, sha = load_corpus(root)
    by_cid = {c.cid: c for c in chunks}
    tasks = build_tasks(chunks, 50, 7, locality=True, far_ref=0.4)
    from ctxfold.runtime import Runtime  # noqa: PLC0415

    # 只取 full 基线与默认配置两条曲线（够说明问题）
    def session_tokens(strict: bool):
        rt = Runtime(corpus=root, state_dir=Path("/tmp/_calib"), strict_visibility=strict)
        full_prompts, our_prompts = [], []
        hist = []
        for t in tasks:
            text = by_cid[t["cid"]].text
            full_prompts.append("\n\n".join(hist + [text]) + "\n\n[问题] " + t["query"])
            hist.append(text)
            r = rt.ask(t["query"])
            our_prompts.append(r["prompt"])
        return full_prompts, our_prompts

    full_p, our_p = session_tokens(False)
    e_full, r_full = sum(est(x) for x in full_p), sum(real(x) for x in full_p)
    e_our, r_our = sum(est(x) for x in our_p), sum(real(x) for x in our_p)
    c_est = 1 - e_our / e_full
    c_real = 1 - r_our / r_full
    print(f"\n绝对 token（full）: 估算 {e_full:,}  真实 {r_full:,}  偏差 {(e_full-r_full)/r_full:+.1%}")
    print(f"绝对 token（ours）: 估算 {e_our:,}  真实 {r_our:,}  偏差 {(e_our-r_our)/r_our:+.1%}")
    print(f"C_cum:  估算 {c_est:.4f}  真实 {c_real:.4f}  差 {abs(c_est-c_real)*100:.2f} 个百分点")

    out["ratio_impact"] = {
        "full_tokens_estimate": e_full, "full_tokens_real": r_full,
        "ours_tokens_estimate": e_our, "ours_tokens_real": r_our,
        "c_cum_estimate": round(c_est, 4), "c_cum_real": round(c_real, 4),
        "c_cum_gap_pp": round(abs(c_est - c_real) * 100, 2),
    }
    run = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-calib")
    run.mkdir(parents=True, exist_ok=True)
    (run / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nrun dir: {run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
