"""检索：BM25（纯词法，无向量、无模型）。

为什么不用向量：
  代码域的"证据"是符号，标识符精确匹配比语义相似更准、更可解释、零成本。
  向量检索留作 v0.2 的模糊查询补充，不作为默认路径。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .chunker import Chunk

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in IDENT.findall(text)]


@dataclass
class BM25:
    chunks: list[Chunk]
    k1: float = 1.2
    b: float = 0.75

    def __post_init__(self) -> None:
        self.docs = [Counter(tokenize(c.name + " " + c.text)) for c in self.chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 1.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(set(d))
        n = max(1, len(self.docs))
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, q: list[str], i: int) -> float:
        d, s = self.docs[i], 0.0
        for t in q:
            f = d.get(t, 0)
            if not f:
                continue
            s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / (
                f + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg)
            )
        return s

    def top_k(self, query: str, k: int = 8, budget: int | None = None) -> list[Chunk]:
        """返回 top-k；若给 budget，则按分数顺序装到 token 预算用完为止（等预算对照）。"""
        q = tokenize(query)
        scored = sorted(((self.score(q, i), i) for i in range(len(self.chunks))), reverse=True)
        out: list[Chunk] = []
        spent = 0
        for sc, i in scored:
            if sc <= 0 and out:
                break
            c = self.chunks[i]
            if budget is not None and out and spent + c.tokens > budget:
                # 预算耗尽即停止（而不是跳过挑更小的碎片：那会偏离"最相关证据"的语义）
                break
            out.append(c)
            spent += c.tokens
            if len(out) >= k:
                break
        return out
