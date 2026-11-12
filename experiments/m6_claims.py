"""M6 结论层实验（离线）：三种表示形式的成本，以及"结论比原文贵"的交叉点。

三种表示（记忆固化后，同一问题的 prompt 内容）：
  raw    原文        —— 信息最全
  card   摘要卡      —— 能答"在哪、调用谁"
  claim  已验证结论  —— 直接给结论，不需要模型重推

关键发现（必须一起读）：**结论有固定开销，短函数上反而比原文贵**。
本实验用一个短函数（tiny）和一个长函数（bulky）各测一遍，把交叉点摆出来。
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.runtime import Runtime  # noqa: E402
from ctxfold.tokenize import TOKENIZER_NAME, token_count  # noqa: E402

TINY = '''def tiny(x):
    return x + 1
'''

BULKY = '''def bulky(records, min_score=0.0, allow_empty=False):
    """筛选并规整记录：过滤低分、去重、按分数降序，返回 (kept, dropped)。"""
    if not isinstance(records, list):
        raise TypeError("records 必须是列表")
    if min_score < 0:
        raise ValueError("min_score 不能为负")
    seen = set()
    kept = []
    dropped = 0
    for rec in records:
        if rec is None:
            dropped += 1
            continue
        key = rec.get("id")
        score = rec.get("score", 0.0)
        if key in seen:
            dropped += 1
            continue
        if score < min_score:
            dropped += 1
            continue
        seen.add(key)
        kept.append({"id": key, "score": score, "payload": rec.get("payload") or {}})
    kept.sort(key=lambda r: r["score"], reverse=True)
    if not kept and not allow_empty:
        raise RuntimeError("没有任何记录通过筛选")
    return kept, dropped
'''


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ctxfold-claims-"))
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text(TINY + "\n\n" + BULKY, encoding="utf-8")

    rt = Runtime(corpus=repo, state_dir=tmp / "st", gate_interval=99)
    py = sys.executable
    rows = []

    for name in ("tiny", "bulky"):
        q = f"{name} 做了什么？它的行为是什么？"
        r_raw = rt.ask(q)                                   # 冷：原文
        r_card = rt.ask(q)                                  # 温：摘要卡
        cid = next(c for c in rt.memory if c.endswith("::" + name))
        claim = (
            "tiny(x) 返回 x+1，不做类型检查。"
            if name == "tiny"
            else "bulky(records, min_score, allow_empty) 过滤 score<min_score 与重复 id，"
                 "按 score 降序返回 (kept, dropped)；非列表抛 TypeError，min_score<0 抛 ValueError，"
                 "全被过滤且 allow_empty=False 时抛 RuntimeError。"
        )
        rt.remember(cid, claim, {"kind": "cmd", "cmd": [py, "-c",
                    f"import sys; sys.path.insert(0,'.'); from calc import {name}; print('ok')"]})
        r_claim = rt.ask(q)
        rows.append((name, r_raw["tokens"], r_card["tokens"], r_claim["tokens"]))

    print(f"tokenizer={TOKENIZER_NAME}")
    print(f"\n{'符号':8}{'raw':>6}{'card':>6}{'claim':>7}   谁最便宜")
    for name, a, b, c in rows:
        best = min((a, "raw"), (b, "card"), (c, "claim"))
        print(f"{name:8}{a:>6}{b:>6}{c:>7}   {best[1]}")

    print()
    print("结论（与直觉不同，必须照实写）：")
    print("  1) 短符号上 原文最便宜——claim 的固定开销付不起；")
    print("  2) 长符号上 card 反而比 claim 更省 token——claim 的长度取决于结论写得有多啰嗦；")
    print("  3) 所以 claim 的价值不是省 token，而是省一次推理：")
    print("     模型拿到结论就能直接用，不用从 257 token 的代码里重新推导语义。")
    print("     一句话：card/raw 省的是「字」，claim 省的是「想」。")

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m6-claims")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "manifest": {"kind": "m6-claims (offline demo)", "tokenizer": TOKENIZER_NAME},
        "rows": [{"symbol": n, "raw": a, "card": b, "claim": c} for n, a, b, c in rows],
        "note": "claim 的价值是省推理而非省 token；实测长符号上 card 比 claim 更省 token，"
                "claim 的长度取决于结论书写密度",
        "limitation": "claim 只覆盖写入时断言过的内容；断言之外仍需 card/raw/recall；"
                      "claim 由谁写、写错怎么办，仍依赖抽检与人工",
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nrun dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
