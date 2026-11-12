"""一键复现全部离线实验（五方法对比 + guard 粒度 + 传播），并生成 experiments/RESULTS.md。

用法：
  python experiments/reproduce.py            # 全量
  python experiments/reproduce.py --quick    # 减少试验次数（CI 用）

不调用任何模型、不需要网络、不需要 GPU。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"
PY = sys.executable


def run(cmd: list[str]) -> str:
    print("$", " ".join(cmd[1:]))
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        print(p.stdout[-2000:])
        print(p.stderr[-2000:])
        raise SystemExit(f"failed: {cmd}")
    return p.stdout


def snapshot() -> set[Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    return {p for p in RUNS.iterdir() if p.is_dir()}


def newest(before: set[Path]) -> Path:
    new = sorted({p for p in RUNS.iterdir() if p.is_dir()} - before, key=lambda p: p.stat().st_mtime)
    if not new:
        raise SystemExit("no new run dir produced")
    return new[-1]


def load(p: Path) -> dict:
    return json.loads((p / "summary.json").read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    trials = "40" if args.quick else "200"
    turns = "20" if args.quick else "50"

    t0 = time.time()
    print(run([PY, "tests/test_core.py"]).strip())

    before = snapshot()
    run([PY, "experiments/m2_baselines.py", "--turns", turns])
    m2 = load(newest(before)); before = snapshot()

    run([PY, "experiments/m1_fingerprint.py", "--turns", "12", "--mutate", "3"])
    f1 = load(newest(before)); before = snapshot()

    run([PY, "experiments/m1_propagation.py", "--turns", "40", "--trials", trials])
    p1 = load(newest(before)); before = snapshot()

    run([PY, "experiments/m7_ablation.py"])
    ab = load(newest(before)); before = snapshot()

    run([PY, "experiments/m2b_isoacc.py", "--turns", turns])
    i1 = load(newest(before))

    t = m2["table"]
    man = m2["manifest"]
    lines = [
        "# 离线实验结果（自动生成，勿手改）",
        "",
        f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}　耗时：{time.time()-t0:.1f}s",
        f"tokenizer：`{man['tokenizer']}`"
        f"{'（估算值，非真实 token）' if man['estimate'] else ''}　"
        f"轮数 {man['turns']}　预算 {man['budget']}　seed {man['seed']}",
        "",
        f"## E1 五种上下文策略对比（{man['turns']} 轮，时间局部性 + 40% 长程引用）",
        "",
        "| 方法 | 总 token | 含全量 recall | C_cum | R_prompt | R_avail | 长程引用 R | 末轮 token |",
        "|---|---|---|---|---|---|---|---|",
    ]
    label = {"full": "full（全量）", "window": "window-5", "summary": "summary（抽取摘要）",
             "grepriag": "grep-RAG（BM25）", "ours": "**ctxfold**"}
    for m in ("full", "window", "summary", "grepriag", "ours"):
        v = t[m]
        lines.append(
            f"| {label[m]} | {v['total_tokens']:,} | {v['total_tokens_allrecall']:,} | "
            f"{v['c_cum']:.3f} | {v['r_prompt']:.3f} | {v['r_avail']:.3f} | "
            f"{v['r_prompt_far']:.3f} | {v['tokens_tlast']:,} |"
        )
    o = t["ours"]; g = t["grepriag"]
    lines += [
        "",
        f"**关键读法（三句都说）**：",
        f"1) 不做 recall：成本 **{o['total_tokens']:,}** token，为 grep-RAG 的 "
        f"**{100*o['total_tokens']/g['total_tokens']:.0f}%**，严格可见证据率 {o['r_prompt']:.3f} vs {g['r_prompt']:.3f}（略低）；",
        f"2) 全部 recall（最坏）：成本 **{o['total_tokens_allrecall']:,}**，比 grep-RAG "
        f"**高 {100*(o['total_tokens_allrecall']/g['total_tokens_allrecall']-1):.0f}%**，可召回证据率 "
        f"{o['r_avail']:.3f} vs {g['r_avail']:.3f}；",
        f"3) 所以本文的卖点不是「同等成本下证据更多」，而是**可召回证据率接近饱和（{o['r_avail']:.3f}）** "
        f"加上「已知内容不重复付费」这一机制。",
        "",
        "## E2 guard 粒度（改 3 个符号）",
        "",
        "| guard | 失效条数 | 需重读 token |",
        "|---|---|---|",
        f"| file | {f1['file_guard']['stale']} | {f1['file_guard']['recomp_tokens']:,} |",
        f"| symbol | {f1['symbol_guard']['stale']} | {f1['symbol_guard']['recomp_tokens']:,} |",
        "",
        f"误失效 {f1['false_positive']} 条 = 记忆的 {f1['fp_rate_of_memory']:.1%}；"
        f"重算成本比 {f1['recomp_tokens_ratio_file_vs_symbol']}×",
        "",
        "## E3 选择性重算（传播 vs 全量失效）",
        "",
        "| 失效 k | 下游污染 | 传播式重算 | 相对全量节省 |",
        "|---|---|---|---|",
    ]
    for k, v in p1["by_k"].items():
        lines.append(
            f"| {k} | {v['suspect_mean']} | {v['cost_prop_mean']:,} | {v['saving_vs_full']:.1%} |"
        )
    sw = i1["grepriag_sweep"]
    lines += [
        "",
        "## E4 等精度切片（iso-accuracy，协议 §3 的另一半）",
        "",
        f"ctxfold（全量 recall）证据率 {i1['ctxfold']['r_avail']:.3f}，成本 {i1['ctxfold']['total_tokens']:,} token。",
        "",
        "| grep-RAG 预算 | 总 token | R_avail |",
        "|---|---|---|",
    ]
    for r in sw:
        lines.append(f"| {r['budget']:,} | {r['total_tokens']:,} | {r['r_avail']:.3f} |")
    if i1["iso_accuracy_hit"]:
        v = i1["verdict"]
        lines += ["", f"等精度点：预算 {v['grepriag_budget_needed']:,} 时成本为 ctxfold 的 "
                      f"**{v['cost_ratio_vs_ctxfold']}×**。"]
    else:
        lines += ["", f"**扫描范围内 grep-RAG 未达到 ctxfold 的证据率**（上限 "
                      f"{max(r['r_avail'] for r in sw):.3f}，此时已花 "
                      f"{max(r['total_tokens'] for r in sw):,} token）。",
                  "归因：gold 含 AST 依赖项，词法检索对其无能为力——这不是调参能修的问题。",
                  "同时必须承认：该结论部分由指标定义决定（gold 来自依赖图），存在循环论证风险。"]
    at = ab["table"]; abase = at["base"]["tokens"]
    lines += [
        "",
        "## E5 消融（同一任务序列，逐个关掉机制）",
        "",
        "| 配置 | 总 token | 相对 base | R_prompt | R_avail | 长程引用 R |",
        "|---|---|---|---|---|---|",
    ]
    for name in ("base", "-closure", "-placeholder", "-card", "-claim", "+full"):
        v = at[name]
        far = v["far_r_prompt"]
        lines.append(
            f"| {name} | {v['tokens']:,} | {v['tokens']/abase:.2f}x | {v['r_prompt']:.3f} | "
            f"{v['r_avail']:.3f} | {('%.3f' % far) if far is not None else '-'} |"
        )
    lines += [
        "",
        f"**三个可操作的结论**：",
        f"1. **闭包是性价比之王**：关掉它省 {100*(1-at['-closure']['tokens']/abase):.0f}% token，"
        f"但可召回率从 {at['base']['r_avail']:.3f} 掉到 {at['-closure']['r_avail']:.3f}；",
        f"2. **占位符是一个显式旋钮**：关掉它（已固化也重发原文）多花 "
        f"{100*(at['-placeholder']['tokens']/abase-1):.0f}% token，换回 "
        f"{100*(at['-placeholder']['r_prompt']-at['base']['r_prompt']):.0f} 个点的严格可见率——"
        f"这就是「可见性 vs 成本」的开关；",
        f"3. **card / claim 在本指标下不可见**（几乎不影响 R），因为 R 只认原文。"
        f"这正说明过程指标对「表示层」是盲的，其价值只能由在线 A 衡量。",
    ]
    lines += [
        "",
        "## 局限（必须与数字同时阅读）",
        "",
        "- token 数为估算时，绝对值有 ±15% 误差；方法间相对比较同基准。",
        "- 任务序列为合成（随机抽符号 + AST 依赖近似 gold），**不属于论文 test 数据**。",
        "- E3 的污染闭包依赖 1-hop 依赖图（含跨文件 import 边），真实工程更密，成本会上升。",
        "- 传播精度、A（正确率）、H（真免算率）、E（在线错误残留率）均需在线实验，此处未测。",
        "- summary 基线用**抽取式**摘要（非模型摘要），对它是偏保守的近似。",
        "",
    ]
    (ROOT / "experiments" / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print()
    print("\n".join(lines[4:16]))
    print(f"\nwritten: {ROOT / 'experiments' / 'RESULTS.md'}  ({time.time()-t0:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
