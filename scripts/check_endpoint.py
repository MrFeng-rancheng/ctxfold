"""check_endpoint：在线实验就绪检查。

回答一个问题：**现在能不能跑真实模型实验？**

三种结果：
  READY      端点可达且能完成一次最小调用 —— 直接跑 m3_online.py --mode real
  NO_KEY     端点可达，但缺 API key —— 只差一把钥匙
  UNREACH    端点不可达 —— 需要换网络环境或换端点

不会打印密钥，只打印是否存在与长度。
"""
from __future__ import annotations

import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold import llm  # noqa: E402

# 常见端点（仅用于连通性探测，不代表推荐）
PROBE = [
    "https://api.deepseek.com/v1/models",
    "https://open.bigmodel.cn/api/paas/v4/models",
    "https://api.moonshot.cn/v1/models",
    "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
    "https://api.openai.com/v1/models",
]


def reachable(url: str, timeout: int = 6) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        # 401/403/404 都说明服务器活着（只是没授权或路径不对）
        return True, f"HTTP {e.code}（可达）"
    except Exception as e:
        return False, type(e).__name__


def main() -> int:
    cfg = llm.config()
    print("=== ctxfold 在线实验就绪检查 ===\n")
    print(f"端点: {cfg['base']}")
    print(f"模型: {cfg['model']}")
    print(f"密钥: {'已设置（长度 %d）' % len(cfg['key']) if cfg['key'] else '未设置'}\n")

    print("网络连通性（常见端点）：")
    any_ok = False
    for u in PROBE:
        ok, note = reachable(u)
        any_ok = any_ok or ok
        host = urllib.parse.urlparse(u).netloc
        print(f"  {'✓' if ok else '✗'} {host:38} {note}")

    print()
    if not cfg["key"]:
        print("结果是 NO_KEY：网络可用，只差 API key。")
        print("设置后即可运行：")
        print("  set CTXFOLD_BASE_URL=https://api.deepseek.com/v1")
        print("  set CTXFOLD_API_KEY=sk-...")
        print("  set CTXFOLD_MODEL=deepseek-chat")
        print("  python experiments/m3_online.py --mode real --tasks 30")
        return 3

    print("尝试一次最小调用…")
    t0 = time.perf_counter()
    try:
        resp = llm.chat([{"role": "user", "content": "回答一个字：好"}])
    except RuntimeError as e:
        print(f"  调用失败：{e}")
        print("\n结果是 UNREACH / BAD_ENDPOINT：密钥已设置但端点调用失败。")
        return 4
    ms = (time.perf_counter() - t0) * 1000
    usage = resp.get("usage", {})
    print(f"  成功，{ms:.0f} ms，usage={usage}")
    print("\n结果是 READY：可以跑真实实验了：")
    print("  python experiments/m3_online.py --mode real --tasks 30")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
