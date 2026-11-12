"""minimal.py —— 30 行看懂 ctxfold 省在哪（不调用模型、不联网）。

跑法（仓库根目录）：
    python examples/minimal.py

它在临时目录造一个 3 函数的小仓库，然后用 CLI 连问两轮，打印每轮的真实 token 数：
第 1 轮读原文，第 2 轮同一问题已固化，原文变成摘要卡与占位符，token 下降。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = """def validate(order):
    return order.get("qty", 0) > 0


def price(order):
    return order["unit"] * order["qty"]


def process_order(order):
    if not validate(order):
        raise ValueError("bad order")
    return price(order)
"""
QUERY = "process_order 是怎么工作的？它调用了什么？"


def ask(corpus, state):
    """调用 CLI 的 --json 模式，拿回 messages 与 meta（这就是交给模型的东西）。"""
    cmd = [sys.executable, "-m", "ctxfold.cli", "--corpus", str(corpus),
           "--state", str(state), "ask", "--json", QUERY]
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         env={**env}, check=True).stdout
    return json.loads(out)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        corpus, state = Path(tmp), Path(tmp) / ".ctxfold"
        (corpus / "order.py").write_text(CODE, encoding="utf-8")
        for turn in (1, 2):
            res = ask(corpus, state)
            meta = res["meta"]
            print("第 %d 轮 token=%s  原文 %d 条  占位符 %d 个  免算=%s" % (
                turn, meta.get("tokens"), len(meta.get("included") or []),
                len(meta.get("placeholders") or []), meta.get("no_model_needed")))
            body = res["messages"][-1]["content"]
            print("  首行出处:", body.splitlines()[0] if body else "（无原文）")
        print(chr(10) + "第二轮的意义：同一段代码没有被重读第二遍。")


if __name__ == "__main__":
    main()
