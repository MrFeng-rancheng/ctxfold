"""Tokenizer 适配层。

原则：token 数是本项目的核心指标，必须可追溯、可复现。

默认使用**字符估算器**（chars/3.5）：零依赖、确定性、任何环境跑出的数字都一样。
需要精确值时设置 `CTXFOLD_TOKENIZER=exact`，改用 tiktoken(cl100k_base)。
两者的关系已量化：见 `scripts/calibrate_tokenizer.py` 与附录 A.13。

重要：C / R / H / E 都是**比值或计数**，同一 tokenizer 对分子分母同比例缩放，
因此估算误差对结论几乎无影响，只影响绝对 token 数。
"""
from __future__ import annotations

TOKENIZER_NAME = ""
_CHARS_PER_TOKEN = 3.5  # 代码语料经验值；接上 tiktoken 后须用真实语料重新校准

import os

_MODE = os.environ.get("CTXFOLD_TOKENIZER", "estimate").strip().lower()

try:  # pragma: no cover - 环境相关
    if _MODE != "exact":
        raise ImportError("estimator mode")
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")
    TOKENIZER_NAME = "tiktoken:cl100k_base"

    def token_count(text: str) -> int:
        return len(_enc.encode(text, disallowed_special=()))

    IS_ESTIMATE = False
except Exception:  # pragma: no cover
    TOKENIZER_NAME = f"estimator:chars/{_CHARS_PER_TOKEN}"

    def token_count(text: str) -> int:
        if not text:
            return 0
        return max(1, round(len(text) / _CHARS_PER_TOKEN))

    IS_ESTIMATE = True


def char_count(text: str) -> int:
    return len(text)
