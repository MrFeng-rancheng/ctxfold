# -*- coding: utf-8 -*-
"""汇总表 4 的四个语料（http50 / json40 / unittest30 / this-repo30），按论文口径输出。"""
import glob
import json
import os
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "experiments", "runs")
TAGS = {"t4http": "标准库 http", "t4json": "标准库 json",
        "t4unit": "标准库 unittest", "t4repo": "本项目源码"}


def main() -> int:
    out = []
    for tag, label in TAGS.items():
        ds = [d for d in glob.glob(os.path.join(RUNS, f"*m3-real-{tag}")) if os.path.isdir(d)]
        ds = [d for d in ds if os.path.exists(os.path.join(d, "rows.jsonl"))]
        if not ds:
            print(f"[pending] {tag}")
            continue
        d = sorted(ds, key=os.path.getmtime)[-1]
        rows = [json.loads(l) for l in open(os.path.join(d, "rows.jsonl"), encoding="utf-8") if l.strip()]
        by_kind = {}
        for r in rows:
            by_kind.setdefault(r["kind"], []).append(r)
        n = len(rows)
        out.append({
            "label": label, "n": n,
            "A": round(sum(1 for r in rows if r["ok"]) / n, 3),
            "H": round(sum(1 for r in rows if r["no_recall_correct"]) / n, 3),
            "recall": round(sum(1 for r in rows if r["recalls"] > 0) / n, 3),
            "locate": round(sum(1 for r in by_kind.get("q_locate", []) if r["ok"])
                            / max(1, len(by_kind.get("q_locate", []))), 3),
            "exc": round(sum(1 for r in by_kind.get("q_exc", []) if r["ok"])
                         / max(1, len(by_kind.get("q_exc", []))), 3),
            "deps_strict": round(sum(1 for r in by_kind.get("q_deps", []) if r["ok"])
                                 / max(1, len(by_kind.get("q_deps", []))), 3),
            "f1": round(st.mean([r["f1"] for r in by_kind.get("q_deps", []) if r.get("f1") is not None] or [0]), 3),
            "f1_repo": round(st.mean([r["f1_repo"] for r in by_kind.get("q_deps", [])
                                      if r.get("f1_repo") is not None] or [0]), 3),
            "deps_empty": sum(1 for r in by_kind.get("q_deps", []) if not r["gold"]),
            "tok": int(st.median(r["tokens"] for r in rows)),
        })
    if not out:
        print("还没数据")
        return 1
    print("%-14s %4s %6s %6s %6s %6s %6s %6s %6s %6s %6s" %
          ("语料", "n", "准确率", "免算率", "取回率", "定位", "语义", "依赖严", "F1", "F1仓", "空题"))
    for r in out:
        print("%-14s %4d %6.3f %6.3f %6.3f %6.3f %6.3f %6.3f %6.3f %6.3f %6d" %
              (r["label"], r["n"], r["A"], r["H"], r["recall"], r["locate"], r["exc"],
               r["deps_strict"], r["f1"], r["f1_repo"], r["deps_empty"]))
    print()
    print("合计 n=%d | 定位 %.3f–%.3f | 语义 %.3f–%.3f | 依赖严 %.3f–%.3f | F1 %.3f–%.3f | 免算 %.3f–%.3f | 取回 %.3f–%.3f"
          % (sum(r["n"] for r in out),
             min(r["locate"] for r in out), max(r["locate"] for r in out),
             min(r["exc"] for r in out), max(r["exc"] for r in out),
             min(r["deps_strict"] for r in out), max(r["deps_strict"] for r in out),
             min(r["f1"] for r in out), max(r["f1"] for r in out),
             min(r["H"] for r in out), max(r["H"] for r in out),
             min(r["recall"] for r in out), max(r["recall"] for r in out)))
    json.dump(out, open(os.path.join(ROOT, "experiments", "RESULTS-t4.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
