# -*- coding: utf-8 -*-
"""汇总两臂（boost=0 / boost=1）的依赖题对比：准确率、仓库内口径 F1、单轮 token。"""
import glob
import json
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "experiments", "runs")


def latest_real(n=2):
    ds = [d for d in glob.glob(os.path.join(RUNS, "*m3-real*")) if os.path.isdir(d)]
    ds.sort(key=os.path.getmtime)
    return ds[-n:]


def load(d):
    summ = json.load(open(os.path.join(d, "summary.json"), encoding="utf-8"))
    rows = []
    p = os.path.join(d, "rows.jsonl")
    if os.path.exists(p):
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return summ, rows


def main() -> int:
    ds = latest_real(2)
    if len(ds) < 2:
        print("run 数不足:", ds)
        return 1
    print(f"对比两个 run：\n  A = {os.path.basename(ds[0])}\n  B = {os.path.basename(ds[1])}\n")
    out = {}
    for tag, d in (("A(boost=0)", ds[0]), ("B(boost=1)", ds[1])):
        summ, rows = load(d)
        deps = [r for r in rows if r.get("kind") == "q_deps"]
        loc = [r for r in rows if r.get("kind") == "q_locate"]
        exc = [r for r in rows if r.get("kind") == "q_exc"]
        m = summ
        out[tag] = {
            "题数": m.get("manifest", {}).get("tasks"),
            "依赖题数": len(deps),
            "依赖 gold 为空": m.get("deps_gold_empty"),
            "定位题准确率": m.get("A_by_kind", {}).get("q_locate"),
            "语义题准确率": m.get("A_by_kind", {}).get("q_exc"),
            "依赖题准确率(严格)": m.get("A_by_kind", {}).get("q_deps"),
            "依赖题准确率(仓库口径)": m.get("A_repo_deps"),
            "依赖题 F1(旧)": m.get("f1_deps_mean"),
            "依赖题 F1(仓库口径)": m.get("f1_repo_deps_mean"),
            "单轮 token": m.get("tokens_mean"),
            "取回率": m.get("recall_rate"),
        }
        if deps:
            out[tag]["依赖题 token 中位"] = round(st.median(r["tokens"] for r in deps))
            out[tag]["依赖题 recall 次数"] = sum(r.get("recalls", 0) for r in deps)
        # 逐题配对（按 cid 对齐）
        out[tag]["_deps_by_cid"] = {r["cid"]: r for r in deps}

    keys = [k for k in out["A(boost=0)"] if not k.startswith("_")]
    print("%-24s %-16s %-16s %s" % ("指标", "A(boost=0)", "B(boost=1)", "变化"))
    for k in keys:
        a, b = out["A(boost=0)"].get(k), out["B(boost=1)"].get(k)
        delta = ""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a:
            delta = "%+.1f%%" % ((b - a) / a * 100)
            if k in ("依赖题准确率(严格)", "依赖题准确率(仓库口径)", "依赖题 F1(旧)", "依赖题 F1(仓库口径)",
                     "定位题准确率", "语义题准确率", "取回率"):
                delta = "%+.3f" % (b - a)
        print("%-24s %-16s %-16s %s" % (k, a, b, delta))

    # 逐题：B 相对 A 的改善/回退
    da = out["A(boost=0)"]["_deps_by_cid"]
    db = out["B(boost=1)"]["_deps_by_cid"]
    common = sorted(set(da) & set(db))
    up = [c for c in common if (db[c].get("f1_repo") or 0) > (da[c].get("f1_repo") or 0)]
    down = [c for c in common if (db[c].get("f1_repo") or 0) < (da[c].get("f1_repo") or 0)]
    print(f"\n逐题（仓库口径 F1）：配对 {len(common)} 题，变好 {len(up)}，变差 {len(down)}")
    for c in up[:5]:
        print(f"  ↑ {c}: {da[c].get('f1_repo')} -> {db[c].get('f1_repo')}")
    for c in down[:5]:
        print(f"  ↓ {c}: {da[c].get('f1_repo')} -> {db[c].get('f1_repo')}")

    json.dump({k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
               for k, v in out.items()},
              open(os.path.join(ROOT, "experiments", "RESULTS-m16-deps-ab.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
