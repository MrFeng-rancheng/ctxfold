"""30 秒演示：在临时目录建一个小仓库，跑「原文 → 免算 → 只重算被改的那一个」。

用法：python scripts/demo.py
不联网、不调用模型，输出可以直接贴进 README。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SRC_V1 = '''def process_order(order, opts):
    for attempt in range(5):
        if validate(order):
            return charge(order)
    raise RuntimeError("retry exhausted")


def validate(order):
    return order.get("id") is not None


def charge(order):
    return {"ok": True, "id": order["id"]}
'''

SRC_V2 = '''def process_order(order, opts):
    for attempt in range(5):
        if validate(order):
            return charge(order)
    raise RuntimeError("retry exhausted")


def validate(order):
    return bool(order.get("id")) and order.get("paid") is not False


def charge(order):
    return {"ok": True, "id": order["id"]}
'''

Q = "process_order 是怎么工作的？它调用了什么？"


def cli(corpus: Path, state: Path, *args: str) -> str:
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run(
        [sys.executable, "-m", "ctxfold.cli", "--corpus", str(corpus), "--state", str(state), *args],
        capture_output=True, text=True, encoding="utf-8", env={**env},
    )
    if p.returncode != 0:
        print(p.stdout, p.stderr)
        raise SystemExit("cli failed")
    return p.stdout


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ctxfold-demo-"))
    repo, state = tmp / "repo", tmp / "state"
    repo.mkdir()
    (repo / "order.py").write_text(SRC_V1, encoding="utf-8")

    def summary(label: str, out: str) -> None:
        head = [l for l in out.splitlines() if l.startswith("#")][:2]
        tok = head[0].split("tokens=")[1].split()[0] if head and "tokens=" in head[0] else "?"
        dec = head[1].replace("# 决策: ", "") if len(head) > 1 else ""
        print(f"{label:<12} tokens={tok:<5} {dec}")

    print(f"demo repo: {repo}")
    print()
    summary("第 1 次问", cli(repo, state, "ask", Q))
    summary("第 2 次问", cli(repo, state, "ask", Q))
    (repo / "order.py").write_text(SRC_V2, encoding="utf-8")
    print("  (改掉 validate() 的实现)")
    summary("第 3 次问", cli(repo, state, "ask", Q))
    print()

    out = cli(repo, state, "ask", Q)
    body = out.split("-" * 60, 1)[1].strip() if "-" * 60 in out else out
    print("第 4 次问，实际发出的 prompt：")
    print("-" * 60)
    print(body)
    print("-" * 60)
    print()
    print("要点：第 3 次只重读了被改的 validate，order/charge 仍是卡片；")
    print("      第 4 次状态已追上世界，回到「什么都不用重读」。")

    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
