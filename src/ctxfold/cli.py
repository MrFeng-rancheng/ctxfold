"""ctxfold 命令行入口。

用法：
  ctxfold --corpus PATH --state DIR init
  ctxfold --corpus PATH --state DIR ask "process_order 是怎么工作的？"
  ctxfold --corpus PATH --state DIR ask --json "..."     # 输出装配好的 messages
  ctxfold --corpus PATH --state DIR status
  ctxfold --corpus PATH --state DIR audit

`ask` 默认只做**装配**（不调用任何模型）：打印将要发送的 prompt 与决策。
--json 输出 messages 数组，可直接喂给任意 OpenAI 兼容客户端。
"""
from __future__ import annotations

import argparse
import json
import sys

from .runtime import Runtime
from .tokenize import IS_ESTIMATE, TOKENIZER_NAME


def _mk(args) -> Runtime:
    return Runtime(corpus=args.corpus, state_dir=args.state, budget=args.budget,
                   guard_level=args.guard, strict_visibility=args.strict)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctxfold", description="有状态推理运行时（装配层，模型无关）")
    ap.add_argument("--corpus", required=True, help="代码库根目录")
    ap.add_argument("--state", default=".ctxfold", help="状态目录（记忆 + 账本）")
    ap.add_argument("--budget", type=int, default=1600, help="单轮证据 token 预算")
    ap.add_argument("--guard", choices=["symbol", "file"], default="symbol")
    ap.add_argument("--strict", action="store_true",
                    help="可见性优先：已固化内容也重发原文（成本约 +41%%，严格可见率 +31pt）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="建立索引（首次使用）")
    p_ask = sub.add_parser("ask", help="装配一轮上下文（不调用模型）")
    p_ask.add_argument("query")
    p_ask.add_argument("--json", action="store_true", help="输出 messages JSON")
    p_ask.add_argument("--no-history", action="store_true")
    sub.add_parser("status", help="查看状态")
    p_doc = sub.add_parser("doctor", help="采用前诊断：这个仓库适不适合 ctxfold")
    p_doc.add_argument("--turns", type=int, default=20)
    p_doc.add_argument("--json", action="store_true")
    sub.add_parser("audit", help="静态抽检所有固化结论")
    args = ap.parse_args(argv)

    rt = _mk(args)
    if IS_ESTIMATE:
        print(f"[warn] tokenizer = {TOKENIZER_NAME}（估算，不是真实 token 数）", file=sys.stderr)

    if args.cmd == "init":
        print(json.dumps(rt.status(), ensure_ascii=False, indent=2))
        rt.save_state()
        return 0

    if args.cmd == "doctor":
        from .doctor import diagnose, render

        d = diagnose(rt.corpus, turns=args.turns)
        print(json.dumps(d.as_dict(), ensure_ascii=False, indent=2) if args.json else render(d))
        return 0

    if args.cmd == "status":
        print(json.dumps(rt.status(), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "audit":
        print(json.dumps(rt.audit_static(), ensure_ascii=False, indent=2))
        return 0

    out = rt.ask(args.query, keep_history=not args.no_history)
    if args.json:
        print(json.dumps({"messages": out["messages"], "meta": {k: out[k] for k in
                          ("tokens", "included", "placeholders", "no_model_needed", "decisions")}},
                         ensure_ascii=False, indent=2))
    else:
        print(f"# tokens={out['tokens']}  免算={out['no_model_needed']}")
        print(f"# 决策: {' | '.join(out['decisions'])}")
        print("-" * 60)
        print(out["prompt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
