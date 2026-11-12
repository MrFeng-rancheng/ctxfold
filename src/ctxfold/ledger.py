"""append-only 账本：所有 commit / stale / suspect / reuse / recall / audit 都留痕。

为什么必须有：
  缓存系统最大的风险是"错误被固化后再也没人重算"。
  账本是唯一能回答"这条结论什么时候进来、依据什么、后来被谁推翻"的东西。
  它同时是可回退性的实现基础（rollback_to）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

KINDS = {"commit", "stale", "suspect", "revive", "reuse", "recall", "audit", "note"}


@dataclass
class Event:
    seq: int
    ts: float
    kind: str
    cid: str | None = None
    detail: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {"seq": self.seq, "ts": self.ts, "kind": self.kind, "cid": self.cid, "detail": self.detail},
            ensure_ascii=False,
        )


class Ledger:
    """JSONL 账本。每次 append 立即落盘（崩溃可恢复）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = sum(1 for _ in self.events())

    def append(self, kind: str, cid: str | None = None, **detail) -> Event:
        if kind not in KINDS:
            raise ValueError(f"unknown event kind: {kind}")
        self._seq += 1
        ev = Event(seq=self._seq, ts=time.time(), kind=kind, cid=cid, detail=detail)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(ev.to_json() + "\n")
        return ev

    def events(self, up_to: int | None = None) -> Iterator[Event]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                if up_to is not None and d["seq"] > up_to:
                    break
                yield Event(seq=d["seq"], ts=d["ts"], kind=d["kind"], cid=d["cid"], detail=d["detail"])

    def replay(self, up_to: int | None = None) -> dict[str, str]:
        """回放得到 cid -> status（fresh/stale/suspect）。"""
        status: dict[str, str] = {}
        for ev in self.events(up_to):
            if not ev.cid:
                continue
            if ev.kind == "commit":
                status[ev.cid] = "fresh"
            elif ev.kind == "stale":
                status[ev.cid] = "stale"
            elif ev.kind == "suspect":
                status[ev.cid] = "suspect"
            elif ev.kind == "revive":
                status[ev.cid] = "fresh"
        return status

    def rollback_to(self, seq: int) -> int:
        """把账本截断到 seq（含），返回保留的事件数。原文件先备份。"""
        keep = [ev.to_json() for ev in self.events(up_to=seq)]
        backup = self.path.with_suffix(self.path.suffix + f".bak-{int(time.time())}")
        if self.path.exists():
            backup.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        self.path.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
        self._seq = len(keep)
        return len(keep)

    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for ev in self.events():
            out[ev.kind] = out.get(ev.kind, 0) + 1
        return out
