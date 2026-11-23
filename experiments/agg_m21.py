# -*- coding: utf-8 -*-
"""汇总 m21（代码修改场景）最新 run：方法 × 场景的 token、陈旧误用、改正与否。"""
from __future__ import annotations

import json
import pathlib
import sys

RUNS = pathlib.Path(__file__).resolve().parents[1] / "experiments" / "runs"
ORDER = ["full", "window", "summary", "grepriag", "ours"]


def main() -> int:
    dirs = sorted(d for d in RUNS.glob("*-m21"))
    if not dirs:
        print("no m21 run")
        return 1
    for d in dirs[-2:]:
        f = d / "summary.json"
        if not f.is_file():
            continue
        rows = json.loads(f.read_text("utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("rows", [])
        print(f"== {d.name}  runs={len(rows)}")
        scen = sorted({r["scenario"].split("（")[0] for r in rows})
        print(f"{'方法':10s}" + "".join(f"{s:>26s}" for s in scen))
        for m in ORDER:
            line = f"{m:10s}"
            for s in scen:
                r = next((x for x in rows if x["method"] == m and x["scenario"].startswith(s)), None)
                if not r:
                    line += f"{'—':>26s}"
                else:
                    tag = "陈旧" if r["stale_misuse"] else ("改正" if r.get("correct_after") else "未改正")
                    line += f"{r['tokens_total']:>8,d} {tag:<6s}{'inv' + str(len(r['invalidated'])):>5s}".rjust(26)
            print(line)
        for s in scen:
            rs = [x for x in rows if x["scenario"].startswith(s)]
            f_ = next((x for x in rs if x["method"] == "full"), None)
            o_ = next((x for x in rs if x["method"] == "ours"), None)
            base = sum(1 for x in rs if x["method"] != "ours" and x["stale_misuse"])
            if f_ and o_:
                print(f"  {s}: 基线陈旧误用 {base}/{len(rs) - 1}，ours 陈旧误用 {int(o_['stale_misuse'])}/1，"
                      f"ours token {o_['tokens_total']:,} / full {f_['tokens_total']:,} = "
                      f"{o_['tokens_total'] / f_['tokens_total']:.1%}")
        tot_o = sum(x["tokens_total"] for x in rows if x["method"] == "ours")
        tot_f = sum(x["tokens_total"] for x in rows if x["method"] == "full")
        print(f"  两场景合计：ours {tot_o:,} / full {tot_f:,} = {tot_o / tot_f:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
