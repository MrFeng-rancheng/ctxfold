"""stub_server：一个最小的 OpenAI 兼容假端点，用来在不花钱的情况下验证 --mode real 全链路。

它不聪明，但足够验证这些环节：
  * HTTP 客户端与请求格式（/chat/completions、Authorization、tools）
  * function calling 的往返（模型发起 tool_call → 客户端回填 tool 消息 → 再次请求）
  * usage 记账、分题型统计、错误处理
  * 装配出来的 prompt 里卡片/占位符是否真的被模型"看见"

回答策略（故意简单、可预测）：
  1) 若 prompt 里有「摘要卡」行 `- #id | path:start-end | ...`，直接把它当答案吐出来（定位题可能答对）；
  2) 若 prompt 里有「未加载」或「可 recall」但本轮还没 recall 过，则发起一次 recall tool_call；
  3) 否则回答 none。

用法：
  python scripts/stub_server.py --port 8799
  CTXFOLD_BASE_URL=http://127.0.0.1:8799/v1 CTXFOLD_API_KEY=stub CTXFOLD_MODEL=stub \\
    python experiments/m3_online.py --mode real --tasks 2
"""
from __future__ import annotations

import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CARD = re.compile(r"- (#\S+) \| ([\w./\\-]+):(\d+)-(\d+)")
ANY_ID = re.compile(r"#([\w./\\-]+::[\w.#]+)")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages", [])
        text = "\n".join(m.get("content") or "" for m in msgs)
        already_recalled = any(m.get("role") == "tool" for m in msgs)

        # 1) 若本轮还在等 recall，给答案（用卡片里的位置，模拟"读到原文后答对"）
        if already_recalled:
            m = CARD.search(text)
            ans = f"{m.group(2)}:{m.group(3)}-{m.group(4)}" if m else "none"
            return self._answer(ans, prompt_tokens=len(text) // 4)

        # 2) 需要取回原文：发起一次 recall
        ids = ANY_ID.findall(text)
        if ids and body.get("tools"):
            call = {
                "id": "call_stub_1",
                "type": "function",
                "function": {"name": "recall", "arguments": json.dumps({"id": ids[0]})},
            }
            return self._payload(
                {"role": "assistant", "content": None, "tool_calls": [call]},
                prompt_tokens=len(text) // 4,
            )

        # 3) 直接回答
        m = CARD.search(text)
        ans = f"{m.group(2)}:{m.group(3)}-{m.group(4)}" if m else "none"
        return self._answer(ans, prompt_tokens=len(text) // 4)

    def _answer(self, content: str, prompt_tokens: int) -> None:
        self._payload({"role": "assistant", "content": content}, prompt_tokens)

    def _payload(self, message: dict, prompt_tokens: int) -> None:
        out = {
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "stub",
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 8,
                "total_tokens": prompt_tokens + 8,
            },
        }
        raw = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    srv = serve(args.port)
    print(f"stub listening on http://127.0.0.1:{args.port}/v1  (Ctrl-C 结束)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
