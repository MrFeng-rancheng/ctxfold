"""把干净批次的 m22 结果写成 markdown 小节，并替换 RESULTS-BEFORE-AFTER.md 的第 7 节。"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = [ROOT / "experiments" / "runs" / f"20261123-{t}-m22" for t in ("013703", "013923", "014138")]
ORDER = ("full", "grepriag", "ours")
LABEL = {"full": "全量历史 full", "grepriag": "BM25 检索 grepriag", "ours": "本文运行时 ours"}


def main() -> int:
    rows: list[dict] = []
    for d in RUNS:
        for r in json.loads((d / "summary.json").read_text("utf-8"))["rows"]:
            rows.append(r)
    tasks = sorted({r["task"] for r in rows}, key=lambda s: int(s.split()[0][1:]))
    reps = {m: max(sum(1 for r in rows if r["method"] == m and r["task"] == t) for t in tasks)
            for m in ORDER}

    def cell(task: str, m: str) -> tuple[int, int, float, float, int]:
        rs = [r for r in rows if r["task"] == task and r["method"] == m]
        if not rs:
            return 0, 0, 0.0, 0.0, 0
        return (sum(1 for r in rs if r["passed"]), len(rs),
                statistics.median([r["tokens"] for r in rs]),
                statistics.median([r["seconds"] for r in rs]),
                sum(r["invalidations"][0] if r["invalidations"] else 0 for r in rs) // len(rs))

    L: list[str] = []
    L.append("## 7. 多步编码任务（m22，11 个任务 × 3 方法 × 3 次重复）")
    L.append("")
    L.append("来源：" + "、".join(f"`runs/{d.name}`" for d in RUNS) + "。")
    L.append("每个（任务，方法）跑 3 次，每次从干净仓库重新注入 bug；通过与否由 `pytest` 退出码判定，"
             "token 为 prompt 计数与 `usage` 之和。任务 T12 因注入 bug 后测试仍通过（不可观测）被跳过。")
    L.append("")
    L.append("| 方法 | n | 通过 | 通过率 | token 均值 | token 中位 | 步数均值 | 耗时均值 | 改动后失效/次 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for m in ORDER:
        rs = [r for r in rows if r["method"] == m]
        n, p = len(rs), sum(1 for r in rs if r["passed"])
        L.append(f"| {LABEL[m]} | {n} | {p} | {p / n:.1%} | {statistics.mean([r['tokens'] for r in rs]):,.0f} "
                 f"| {statistics.median([r['tokens'] for r in rs]):,.0f} "
                 f"| {statistics.mean([r['steps'] for r in rs]):.2f} "
                 f"| {statistics.mean([r['seconds'] for r in rs]):.1f} s "
                 f"| {statistics.mean([len(r['invalidations']) for r in rs]):.2f} |")
    L.append("")
    L.append("逐任务（通过次数 / token 中位）：")
    L.append("")
    L.append("| 任务 | full | grepriag | ours |")
    L.append("|---|---|---|---|")
    for t in tasks:
        cells = []
        for m in ORDER:
            p, n, tk, _, _ = cell(t, m)
            cells.append(f"{p}/{n} · {tk:,.0f}")
        L.append(f"| {t} | " + " | ".join(cells) + " |")
    L.append("")

    stable = [t for t in tasks if sum(1 for r in rows if r["task"] == t and r["method"] == "full" and r["passed"]) > 0]
    L.append(f"可解子集（full 至少一次通过的 {len(stable)} 个任务）：")
    L.append("")
    L.append("| 方法 | n | 通过率 | token 均值 |")
    L.append("|---|---|---|---|")
    for m in ORDER:
        rs = [r for r in rows if r["method"] == m and r["task"] in stable]
        p = sum(1 for r in rs if r["passed"])
        L.append(f"| {LABEL[m]} | {len(rs)} | {p / len(rs):.1%} | "
                 f"{statistics.mean([r['tokens'] for r in rs]):,.0f} |")
    L.append("")
    L.append("读法：")
    L.append("")
    L.append("- ours 与 full 的通过率差距在噪声内（子集 95.2% 对 90.5%），但 token 少 45%（2 710 对 4 956），"
             "步数更少（1.61 对 1.91），说明优势在成本而非命中率。")
    L.append("- grepriag 在 11 个任务里只过 3 次，全部来自 T11；BM25 按失败文本召回，"
             "拿不到\"改哪一行\"的定位信息，补丁里 `old` 片段对不上，于是反复重试。")
    L.append("- T9（快照键唯一性）上 full 只过 1/3，ours 过 3/3：任务要改的正是 ctxfold 自己的状态模块，"
             "全文塞进 prompt 反而让模型在长文件里挑错窗口。")
    L.append("- T3 / T7 / T8 三方全败（需要猜出精确字符串或块标题写法），属任务设计导致的不可解，不计入方法比较；"
             "任务是自行注入的 1–2 行 bug，不是真实 issue，规模 11 个、单模型 `DeepSeek-V3.2`。")
    L.append("")
    section = "\n".join(L)

    target = ROOT / "experiments" / "RESULTS-BEFORE-AFTER.md"
    text = target.read_text("utf-8")
    idx = text.find("## 7. 多步编码任务")
    if idx < 0:
        text = text.rstrip() + "\n\n" + section
    else:
        text = text[:idx] + section
    target.write_text(text, "utf-8")
    (ROOT / "experiments" / "m22_section.md").write_text(section, "utf-8")
    print(section)
    print(f"\n[写回] {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
