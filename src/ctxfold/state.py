"""显式状态机 S = (C, G, D, L)：把核心逻辑从任何 Agent 的提示词里剥离出来。

四元组的含义
  C（Conclusions）  已验证结论：cid -> {claim, verifier, committed_at}
  G（Guards）       守卫条件：cid -> {chunk_sha, file_sha, status}（status ∈ fresh/stale）
  D（Dependencies） 1 跳依赖闭包：cid -> [它调用的 cid]（反向表 dependents 一并提供）
  L（Levels）       上一轮每个 cid 的表示层级：raw / card / claim / placeholder

这个模块不读任何提示词、不依赖会话约定、不调用模型。任何宿主（CLI、DSH 插件、
MCP 服务、别的 agent 框架）都通过下面的方法或 service.py 的 JSON 接口调用它。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .assembler import assemble
from .runtime import Runtime
from .tokenize import token_count

LEVELS = ("raw", "card", "claim", "placeholder")


@dataclass
class StateRuntime:
    """有状态装配运行时：状态是显式的，装配是纯函数式的，取回按 ID 稳定。"""

    corpus: Path
    state_dir: Path
    budget: int = 1600
    guard_level: str = "symbol"       # symbol（细）| file（粗）
    strict_visibility: bool = False
    rt: Runtime | None = None
    levels: dict[str, str] = field(default_factory=dict)

    # ---------- 生命周期 ----------
    def __post_init__(self) -> None:
        self.rt = Runtime(
            corpus=Path(self.corpus),
            state_dir=Path(self.state_dir),
            budget=self.budget,
            guard_level=self.guard_level,
            strict_visibility=self.strict_visibility,
        )
        self.rt.sync_world()

    # ---------- 四元组视图 ----------
    @property
    def C(self) -> dict[str, dict]:
        return {
            cid: {"claim": m.claim, "verifier": m.verifier}
            for cid, m in self.rt.memory.items()
            if m.claim
        }

    @property
    def G(self) -> dict[str, dict]:
        return {
            cid: {"chunk_sha": m.chunk_sha, "file_sha": m.file_sha, "status": m.status}
            for cid, m in self.rt.memory.items()
        }

    @property
    def D(self) -> dict[str, list[str]]:
        return {cid: list(getattr(ck, "deps", []) or []) for cid, ck in self.rt.by_cid.items()}

    @property
    def dependents(self) -> dict[str, list[str]]:
        rev: dict[str, list[str]] = {}
        for cid, deps in self.D.items():
            for dep in deps:
                rev.setdefault(dep, []).append(cid)
        return rev

    @property
    def L(self) -> dict[str, str]:
        return dict(self.levels)

    def snapshot(self) -> dict:
        return {
            "corpus": str(self.rt.corpus),
            "budget": self.budget,
            "guard_level": self.guard_level,
            "S": {"C": self.C, "G": self.G, "D": {k: v for k, v in self.D.items() if v}, "L": self.L},
            "counts": {
                "conclusions": len(self.C),
                "guards": len(self.G),
                "edges": sum(len(v) for v in self.D.values()),
                "fresh": sum(1 for m in self.rt.memory.values() if m.status == "fresh"),
                "stale": sum(1 for m in self.rt.memory.values() if m.status == "stale"),
            },
        }

    # ---------- 装配 ----------
    def assemble(self, query: str, budget: int | None = None) -> dict:
        res = assemble(
            method="ours",
            query=query,
            history=self.rt.history,
            chunks_by_cid=self.rt.by_cid,
            index=self.rt.index,
            memory=self.rt.memory,
            current_sha=self.rt.file_sha,
            budget=budget or self.budget,
            guard_level=self.guard_level,
            ablate=frozenset({"placeholder"}) if self.strict_visibility else frozenset(),
        )
        self.rt.history.append(res.history_append)

        # 记录 L：把本轮每个 cid 的表示层级写进状态
        self.levels = {}
        for cid in res.included_cids:
            self.levels[cid] = "raw"
        for cid in res.claim_cids:
            self.levels[cid] = "claim"
        for cid in res.card_cids:
            self.levels[cid] = "card"
        for cid in res.placeholder_cids:
            self.levels[cid] = "placeholder"

        raw_blocks = []
        for cid in res.included_cids:
            ck = self.rt.by_cid[cid]
            raw_blocks.append({
                "cid": cid,
                "path": ck.path,
                "start": ck.start,
                "end": ck.end,
                "header": f"### #{cid} | {ck.path}:{ck.start}-{ck.end}",
            })

        self.rt.save_state()
        return {
            "prompt": res.prompt,
            "tokens": token_count(res.prompt),
            "no_model_needed": res.no_model_needed,
            "raw_blocks": raw_blocks,
            "placeholders": list(res.placeholder_cids),
            "levels": self.L,
            "decisions": res.decisions,
            "messages": [{"role": "user", "content": res.prompt}],
        }

    # ---------- 按 ID 取回原文（稳定接口） ----------
    def recall(self, cid: str) -> dict:
        ck = self.rt.by_cid.get(cid)
        if ck is None:
            raise KeyError(f"unknown cid: {cid}")
        mem = self.rt.memory.get(cid)
        stored = mem.chunk_sha if mem is not None else ""
        return {
            "cid": cid,
            "path": ck.path,
            "start": ck.start,
            "end": ck.end,
            "text": ck.text,
            "tokens": ck.tokens,
            "header": f"### #{cid} | {ck.path}:{ck.start}-{ck.end}",
            "sha_now": ck.text_sha,
            "sha_stored": stored,
            "unchanged": (not stored) or (stored == ck.text_sha),
        }

    # ---------- 结论与失效 ----------
    def commit(self, cid: str, claim: str, verifier: dict | None = None) -> dict:
        self.rt.remember(cid, claim, verifier)
        self.rt.save_state()
        return {"cid": cid, "claim": claim, "committed": True}

    def invalidate(self) -> dict:
        """重新读盘、按内容哈希判定失效，并沿 1 跳依赖把影响面算出来。

        返回 invalidated（自身变了的）、downstream（依赖它们因而受波及的）、kept（可继续复用）。
        """
        self.rt.load()
        invalidated: list[str] = []
        for cid, mem in self.rt.memory.items():
            ck = self.rt.by_cid.get(cid)
            if ck is None or (mem.chunk_sha and ck.text_sha != mem.chunk_sha):
                mem.status = "stale"
                invalidated.append(cid)

        rev = self.dependents
        downstream: set[str] = set()
        for cid in invalidated:
            for dep in rev.get(cid, []):
                if dep in self.rt.memory and dep not in invalidated:
                    downstream.add(dep)
        for cid in downstream:                     # 下游一并标记，等待重算
            self.rt.memory[cid].status = "stale"

        kept = sorted(c for c, m in self.rt.memory.items()
                      if m.status == "fresh" and c not in invalidated and c not in downstream)
        self.rt.save_state()
        return {"invalidated": sorted(invalidated), "downstream": sorted(downstream), "kept": kept}

    # ---------- 状态 ----------
    def status(self) -> dict:
        st = self.rt.status()
        st["S_counts"] = self.snapshot()["counts"]
        st["levels"] = dict(sorted(self.L.items())[:100])
        return st
