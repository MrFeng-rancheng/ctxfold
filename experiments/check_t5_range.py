# -*- coding: utf-8 -*-
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
rows = json.load(open(r"experiments\runs\20261123-123514-m12\summary.json", encoding="utf-8"))["rows"]
A = [r["A"] for r in rows]
H = [r["H"] for r in rows]
R = [r["recall_rate"] for r in rows]
print("格数", len(rows), "总题", sum(r["n"] for r in rows))
print("A 精确 min/max", min(A), max(A), "-> 两位", f"{min(A):.2f}-{max(A):.2f}", "三位", f"{min(A):.3f}-{max(A):.3f}")
print("H 精确 min/max", min(H), max(H), "-> 两位", f"{min(H):.2f}-{max(H):.2f}", "三位", f"{min(H):.3f}-{max(H):.3f}")
print("R 精确 min/max", min(R), max(R), "-> 两位", f"{min(R):.2f}-{max(R):.2f}", "三位", f"{min(R):.3f}-{max(R):.3f}")
print()
for r in sorted(rows, key=lambda x: x["A"]):
    print(f"  {r['corpus']:5s} {r['model']:15s} n={r['n']:3d} A={r['A']:.4f} H={r['H']:.4f} R={r['recall_rate']:.4f}")
print()
print("表 5 展示值（3 位）最小/最大：", f"{min(A):.3f}", f"{max(A):.3f}")
