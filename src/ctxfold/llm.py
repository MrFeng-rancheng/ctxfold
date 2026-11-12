"""模型客户端：任何 OpenAI 兼容端点（OpenAI / DeepSeek / Qwen / vLLM / Ollama / 本地代理）。

刻意不依赖任何 SDK：
  * 只用标准库 urllib，pip install 零依赖
  * 端点、模型、密钥全部来自环境变量，不写入代码
  * 支持 function calling（recall 工具需要）

环境变量：
  CTXFOLD_BASE_URL   例：https://api.deepseek.com/v1 或 http://localhost:11434/v1
  CTXFOLD_API_KEY    本地模型可留空
  CTXFOLD_MODEL      例：deepseek-chat / qwen2.5-coder:7b
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env_file() -> list[str]:
    """从本地凭据文件加载环境变量（不覆盖已有值，不打印内容）。

    查找顺序：./.secrets.env → 仓库根 .secrets.env → ~/.ctxfold.env
    文件格式：每行 KEY=VALUE，支持 # 注释与引号。
    """
    loaded: list[str] = []
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".secrets.env",
        here.parents[2] / ".secrets.env",
        Path.home() / ".ctxfold.env",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
                    loaded.append(k)
        except OSError:
            continue
        break
    return loaded


def config() -> dict:
    load_env_file()
    return {
        "base": (os.environ.get("CTXFOLD_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
                 or "https://api.openai.com/v1").rstrip("/"),
        "key": os.environ.get("CTXFOLD_API_KEY") or os.environ.get("OPENAI_API_KEY") or "",
        "model": os.environ.get("CTXFOLD_MODEL", "gpt-4o-mini"),
    }


def available() -> bool:
    c = config()
    return bool(c["model"]) and (
        bool(c["key"]) or "localhost" in c["base"] or "127.0.0.1" in c["base"]
    )


def chat(messages: list[dict], tools: list[dict] | None = None, timeout: int = 120,
         max_tokens: int = 1024) -> dict:
    """返回原始响应 dict（含 choices[0].message 与 usage）。"""
    c = config()
    payload = {"model": c["model"], "messages": messages, "temperature": 0,
               "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    req = urllib.request.Request(
        c["base"] + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {c['key']}"} if c["key"] else {}),
        },
    )
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 4xx 通常不可重试（鉴权/参数问题），5xx 与 429 可重试
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
            last = e
        except urllib.error.URLError as e:
            last = e
        except (TimeoutError, socket.timeout) as e:   # 读超时：重试
            last = e
        except Exception as e:                         # 兜底，绝不让单次调用炸掉整轮实验
            last = e
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"调用失败（已重试 3 次）：{type(last).__name__}: {last}")


RECALL_TOOL = {
    "type": "function",
    "function": {
        "name": "recall",
        "description": ("按 id 取回上下文中未加载内容的逐字原文。"
                        "id 必须从上下文里 # 之后原样复制（形如 client.py::Class.method），不要自己拼。"),
        "parameters": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "占位符里给出的 id，例如 order.py::process_order"}},
            "required": ["id"],
        },
    },
}
