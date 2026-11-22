"""本地标准服务接口：一行一个 JSON 请求，一行一个 JSON 响应（stdio）。

存在的理由：核心状态机不能藏在某个 Agent 的 Skill 提示词里。任何宿主——DSH 插件、
MCP 桥、Claude Code、Cursor、自研 agent、甚至一个 bash 脚本——都通过同一组 op 调用它：

  {"id": 1, "op": "assemble", "args": {"query": "add 做了什么"}}
  {"id": 2, "op": "recall",   "args": {"cid": "calc.py::add"}}
  {"id": 3, "op": "invalidate"}
  {"id": 4, "op": "snapshot"}

可用 op：assemble / recall / commit / invalidate / snapshot / status / ping / close
模型只负责"问问题"和"读结果"，不负责记账、算哈希、判断失效——那是本模块的事。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .state import StateRuntime


def handle(state: StateRuntime, req: dict) -> dict:
    op = req.get("op", "")
    args = req.get("args") or {}
    if op == "ping":
        return {"pong": True}
    if op == "assemble":
        return state.assemble(args["query"], budget=args.get("budget"))
    if op == "recall":
        return state.recall(args["cid"])
    if op == "commit":
        return state.commit(args["cid"], args["claim"], args.get("verifier"))
    if op == "invalidate":
        return state.invalidate()
    if op == "snapshot":
        return state.snapshot()
    if op == "status":
        return state.status()
    raise ValueError(f"unknown op: {op}")


def serve(stdin, stdout, state: StateRuntime) -> int:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            stdout.write(json.dumps({"ok": False, "error": f"bad json: {e}"}) + "\n")
            stdout.flush()
            continue
        rid = req.get("id")
        try:
            result = handle(state, req)
            stdout.write(json.dumps({"id": rid, "ok": True, "result": result},
                                    ensure_ascii=False) + "\n")
        except Exception as e:  # 服务不因单条请求崩掉
            stdout.write(json.dumps({"id": rid, "ok": False,
                                     "error": f"{type(e).__name__}: {e}"},
                                    ensure_ascii=False) + "\n")
        stdout.flush()
        if req.get("op") == "close":
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctxfold-serve", description="ctxfold 本地状态服务（stdio JSON）")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--state", default=".ctxfold")
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--guard", choices=["symbol", "file"], default="symbol")
    a = ap.parse_args(argv)
    state = StateRuntime(Path(a.corpus), Path(a.state), budget=a.budget, guard_level=a.guard)
    return serve(sys.stdin, sys.stdout, state)


if __name__ == "__main__":
    raise SystemExit(main())
