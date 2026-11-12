"""抽检（audit）：唯一能发现"已固化错误"的机制。

设计要点：
  * 确定性抽样：hash(cid + epoch) —— 同一实验可重放，不同 seed 可复现
  * 只抽"可被外部验证"的结论（代码域的 T0/T1），不可验证的不抽（抽了也判不了）
  * 记录 verdict 进账本，算 E（错误残留率）= 判错数 / 抽检数
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from .ledger import Ledger


def _stable_hash(s: str, salt: str) -> int:
    h = hashlib.sha256(f"{salt}|{s}".encode("utf-8")).hexdigest()
    return int(h[:12], 16)


@dataclass
class Auditor:
    rate: float = 0.03
    salt: str = "v0"
    ledger: Ledger | None = None
    audited: int = 0
    failed: int = 0
    history: list[dict] = field(default_factory=list)

    def should_audit(self, cid: str) -> bool:
        if self.rate <= 0:
            return False
        return _stable_hash(cid, self.salt) % 10_000 < self.rate * 10_000

    def record(self, cid: str, verdict: str, verifier: str, cost_tokens: int = 0) -> None:
        """verdict: pass | fail"""
        self.audited += 1
        if verdict == "fail":
            self.failed += 1
        self.history.append(
            {"cid": cid, "verdict": verdict, "verifier": verifier, "cost_tokens": cost_tokens}
        )
        if self.ledger is not None:
            self.ledger.append("audit", cid, verdict=verdict, verifier=verifier, cost=cost_tokens)

    @property
    def error_rate(self) -> float | None:
        """E：错误残留率。无抽检时返回 None，不谎报 0。"""
        if self.audited == 0:
            return None
        return self.failed / self.audited

    def escalate(self, threshold: float = 0.10) -> bool:
        """分歧率超阈值则建议整体降级信任（调用方据此把 T1 降 T2）。"""
        e = self.error_rate
        return e is not None and e > threshold
