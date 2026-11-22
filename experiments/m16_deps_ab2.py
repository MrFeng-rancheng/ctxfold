# -*- coding: utf-8 -*-
"""A/B 汇总（按 tag 区分两臂）：三类题准确率、依赖题两种口径 F1、单轮 token。

额外给一个"清洗口径"：把答案里那些其实来自题面或卡片元词的标识符
（calls / repo / ext / 函数 / 摘要卡 …）剔掉后再算 F1，用来区分
"模型没答对" 和 "模型答了但被散文词污染"。
"""
import ast as pyast
import glob
import json
import os
import re
import statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "experiments", "runs")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
META = {"calls", "call", "repo", "ext", "id", "def", "return", "none", "the", "and", "or",
        "function", "functions", "signature", "card", "placeholder", "raw"}


def idents(text: str) -> set[str]:
    return {t.lower() for t in IDENT.findall(text or "")} - META


def cleaned(rows):
    """剔除来自题面本身的标识符（例如问的符号名），只留模型自己列的。"""
    out = []
    for r in rows:
        q_ids = idents(r.get("query", "")) | {r["cid"].split("::")[-1].split(".")[-1].lower()}
        out.append({k: v for k, v in r.items()} | {"got_clean": idents(r.get("answer", "")) - q_ids})
    return out


def f1_of(got: set[str], gold: set[str]) -> float:
    if not gold:
        return 1.0 if not got else 0.0
    tp = len(got & gold)
    if not tp:
        return 0.0
    p, r = tp / len(got), tp / len(gold)
    return 2 * p * r / (p + r)


def load(prefix: str):
    ds = [d for d in glob.glob(os.path.join(RUNS, f"*m3-real-{prefix}")) if os.path.isdir(d)]
    ds = [d for d in ds if os.path.exists(os.path.join(d, "summary.json"))
          and os.path.exists(os.path.join(d, "rows.jsonl"))]
    if not ds:
        return None, []
    d = sorted(ds, key=os.path.getmtime)[-1]
    summ = json.load(open(os.path.join(d, "summary.json"), encoding="utf-8"))
    p = os.path.join(d, "rows.jsonl")
    rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []
    return summ, rows


def stats(rows):
    deps = [r for r in rows if r["kind"] == "q_deps"]
    d = {"定位准确率": None, "语义准确率": None,
         "依赖严格准确率": None, "依赖F1(旧)": None, "依赖F1(只算仓库名)": None,
         "依赖F1(清洗后)": None, "依赖token中位": None, "依赖取回次数": None, "题数": len(rows)}
    if not deps:
        return d
    golds = [{g.lower() for g in (r["gold"] if isinstance(r["gold"], list) else [])} for r in deps]
    d["依赖严格准确率"] = round(sum(1 for r in deps if r["ok"]) / len(deps), 3)
    d["依赖F1(旧)"] = round(st.mean(r.get("f1") or 0 for r in deps), 3)
    d["依赖F1(只算仓库名)"] = round(st.mean(r.get("f1_repo") or 0 for r in deps), 3)
    rows_c = cleaned(deps)
    repo_names = set()
    for r, g in zip(rows_c, golds):
        repo_names |= g
    f1c = []
    for r, g in zip(rows_c, golds):
        got = r["got_clean"]
        # 只保留"看起来是仓库符号"的：出现在 gold 里，或与 gold 共享词根
        got2 = {x for x in got if x in g or any(x in y or y in x for y in g)}
        f1c.append(f1_of(got2, g))
    d["依赖F1(清洗后)"] = round(st.mean(f1c), 3)
    d["依赖token中位"] = int(st.median(r["tokens"] for r in deps))
    d["依赖取回次数"] = sum(r.get("recalls", 0) for r in deps)
    for kind, key in (("q_locate", "定位准确率"), ("q_exc", "语义准确率")):
        rs = [r for r in rows if r["kind"] == kind]
        if rs:
            d[key] = round(sum(1 for r in rs if r["ok"]) / len(rs), 3)
    return d


def main() -> int:
    A = load("A0")
    B = load("B1")
    if not A[1] or not B[1]:
        print("两臂数据还没齐：", "A0", len(A[1]), "B1", len(B[1]))
        return 1
    da, db = stats(A[1]), stats(B[1])
    print("%-22s %-14s %-14s %s" % ("指标", "A(boost=0)", "B(boost=1)", "变化"))
    for k in da:
        a, b = da[k], db[k]
        delta = ""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a:
            delta = "%+.1f%%" % ((b - a) / a * 100) if k.endswith("token中位") else "%+.3f" % (b - a)
        print("%-22s %-14s %-14s %s" % (k, a, b, delta))
    json.dump({"A": da, "B": db}, open(os.path.join(ROOT, "experiments", "RESULTS-m16-deps-ab.json"), "w",
                                       encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
