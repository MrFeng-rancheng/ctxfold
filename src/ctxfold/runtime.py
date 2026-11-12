"""Runtime：把 chunker / assembler / ledger / audit 串成一个有状态的会话对象。

这是"工具"的本体：它记住已经固化了什么、什么时候失效、每次发多少 token。
纯 CPU、无网络、不依赖任何模型 SDK —— 装配结果就是一个 messages 数组，
交给任意模型客户端发送即可（模型无关性的实现方式）。
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .assembler import Memory, assemble
from .audit import Auditor
from .chunker import Chunk, build_symbol_index, chunk_file, chunk_repo, resolve_dependencies
from .ledger import Ledger
from .world import cheap_fingerprint
from .tokenize import TOKENIZER_NAME, token_count


@dataclass
class Runtime:
    corpus: Path
    state_dir: Path
    budget: int = 1600
    guard_level: str = "symbol"  # symbol（默认，细粒度）| file（粗）
    gate_interval: int = 1       # 每 N 轮做一次世界指纹；大仓库（>1000 文件）建议 5~10
    strict_visibility: bool = False  # True=已固化内容也重发原文（可见性优先，成本 +41%）

    chunks: list[Chunk] = field(default_factory=list)
    index: dict[str, str] = field(default_factory=dict)
    by_cid: dict[str, Chunk] = field(default_factory=dict)
    file_sha: dict[str, str] = field(default_factory=dict)
    memory: dict[str, Memory] = field(default_factory=dict)
    ledger: Ledger | None = None
    auditor: Auditor | None = None
    history: list[str] = field(default_factory=list)
    world_fp: str = ""          # 廉价世界指纹（mtime/size），只用于"是否要重新读盘"
    _gate_hits: int = 0          # 门命中次数（世界没变 -> 跳过全库重读）
    _gate_misses: int = 0
    _turns_since_gate: int = 0

    # ---------- 生命周期 ----------
    def __post_init__(self) -> None:
        self.corpus = Path(self.corpus)
        self.state_dir = Path(self.state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.state_dir / "ledger.jsonl")
        self.auditor = Auditor(rate=0.03, ledger=self.ledger)
        self.load()
        self.load_state()

    def load(self) -> None:
        self.chunks = chunk_repo(self.corpus)
        self.index = build_symbol_index(self.chunks)
        resolve_dependencies(self.chunks, self.index)
        self.by_cid = {c.cid: c for c in self.chunks}
        self.file_sha = {c.path: c.file_sha for c in self.chunks}

    def state_path(self) -> Path:
        return self.state_dir / "state.json"

    def load_state(self) -> None:
        p = self.state_path()
        if not p.exists():
            return
        d = json.loads(p.read_text(encoding="utf-8"))
        for cid, m in d.get("memory", {}).items():
            self.memory[cid] = Memory(**m)
        self.history = d.get("history", [])

    def save_state(self) -> None:
        d = {
            "tokenizer": TOKENIZER_NAME,
            "budget": self.budget,
            "guard_level": self.guard_level,
            "strict_visibility": self.strict_visibility,
            "memory": {cid: asdict(m) for cid, m in self.memory.items()},
            "history": self.history[-200:],
        }
        self.state_path().write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")

    # ---------- 主流程 ----------
    def sync_world(self) -> bool:
        """世界变了才重新读盘。返回是否真的重读了。

        廉价门只用于**跳过**，不参与失效判定：误报的代价是"多读一次盘"，
        漏报的代价是"用了错的结论"——所以门宁可误报。
        """
        if not self.chunks:
            self.load()
            self.world_fp = cheap_fingerprint(self.corpus)
            return True
        if self._turns_since_gate < self.gate_interval:
            self._turns_since_gate += 1
            self._gate_hits += 1
            return False
        self._turns_since_gate = 0
        fp = cheap_fingerprint(self.corpus)
        if fp == self.world_fp:
            self._gate_hits += 1
            return False
        self._gate_misses += 1
        self.world_fp = fp
        self.load()
        return True

    def ask(self, query: str, keep_history: bool = True, audit: bool = True) -> dict:
        self.sync_world()
        if audit:
            self.audit_sample()   # 先用抽检补掉节流门可能漏掉的变化
        res = assemble(
            method="ours",
            query=query,
            history=self.history,
            chunks_by_cid=self.by_cid,
            index=self.index,
            memory=self.memory,
            current_sha=self.file_sha,
            budget=self.budget,
            guard_level=self.guard_level,
            ablate=frozenset({"placeholder"}) if self.strict_visibility else frozenset(),
        )
        if keep_history:
            self.history.append(res.history_append)

        # 记账
        for cid in res.included_cids:
            self.ledger.append("commit", cid, via="ask", query=query[:80])
        for cid, mem in self.memory.items():
            if mem.status == "stale":
                self.ledger.append("stale", cid, guard=self.guard_level)
        if res.placeholder_cids:
            self.ledger.append(
                "reuse", None, n=len(res.placeholder_cids), query=query[:80]
            )

        out = {
            "prompt": res.prompt,
            "tokens": token_count(res.prompt),
            "included": res.included_cids,
            "placeholders": res.placeholder_cids,
            "no_model_needed": res.no_model_needed,
            "decisions": res.decisions,
            "messages": [{"role": "user", "content": res.prompt}],
        }
        self.save_state()
        return out

    # ---------- 校验 ----------
    def audit_static(self) -> dict:
        """离线抽检：用静态验证器检查每条固化结论是否仍成立（hash/符号存在性）。"""
        self.load()  # 重新读盘，反映"世界变了"
        checked = passed = failed = 0
        for cid, mem in self.memory.items():
            ck = self.by_cid.get(cid)
            ok = ck is not None and (not mem.chunk_sha or ck.text_sha == mem.chunk_sha)
            checked += 1
            passed += int(ok)
            failed += int(not ok)
            self.auditor.record(cid, "pass" if ok else "fail", "static:hash", cost_tokens=0)
        self.save_state()
        return {
            "checked": checked,
            "pass": passed,
            "fail": failed,
            "E_static": (failed / checked) if checked else None,
            "auditor_error_rate": self.auditor.error_rate,
        }

    def remember(self, cid: str, claim: str, verifier: dict | None = None) -> None:
        """把一条结论连同"如何验证它"一起固化。

        这是"可验证优先"原则的入口：能给出可执行校验器的结论，才配上 T1 以上信任档。
        """
        if cid not in self.memory:
            ck = self.by_cid.get(cid)
            if ck is None:
                raise KeyError(f"unknown cid: {cid}")
            self.memory[cid] = Memory(
                cid=cid, name=ck.name, file_sha=ck.file_sha, chunk_sha=ck.text_sha
            )
        self.memory[cid].claim = claim
        self.memory[cid].verifier = verifier
        self.ledger.append("commit", cid, via="remember", claim=claim[:120],
                           has_verifier=bool(verifier))
        self.save_state()

    def _run_verifier(self, verifier: dict, timeout: int = 30) -> bool:
        """跑可执行校验器。返回 True 表示结论仍成立。"""
        kind = verifier.get("kind")
        if kind != "cmd":
            return False
        cmd = verifier.get("cmd") or []
        if not cmd:
            return False
        try:
            p = subprocess.run(
                cmd, cwd=str(self.corpus), capture_output=True, text=True,
                timeout=timeout, encoding="utf-8",
            )
            return p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _verify_one(self, cid: str) -> bool:
        """对单条记忆做静态校验：只读它所属的那一个文件，重切后比对符号哈希。

        不依赖 self.by_cid（那可能是节流门跳过后留下的旧快照）。
        """
        mem = self.memory[cid]
        if mem.verifier is not None:
            return self._run_verifier(mem.verifier)  # 有可执行校验器 -> 动态验证
        path = self.corpus / cid.split("::")[0]
        if not path.exists():
            return False
        try:
            fresh = chunk_file(path, self.corpus)
        except Exception:
            return False
        for ck in fresh:
            if ck.cid == cid:
                return (not mem.chunk_sha) or ck.text_sha == mem.chunk_sha
        return False  # 符号消失了

    def audit_sample(self, rate_override: float | None = None) -> dict:
        """抽检：细粒度补漏。

        世界指纹是**粗粒度批处理**（每 N 轮一次，存在失效窗口）；
        抽检是**细粒度随机抽样**（每轮看一小部分），二者互补。
        """
        checked = failed = 0
        for cid, mem in list(self.memory.items()):
            hit = True if rate_override is not None else self.auditor.should_audit(cid)
            if not hit:
                continue
            ok = self._verify_one(cid)
            kind = "dynamic:cmd" if self.memory[cid].verifier else "static:symbol_hash"
            self.auditor.record(cid, "pass" if ok else "fail", kind)
            checked += 1
            if not ok:
                failed += 1
                mem.status = "stale"
                self.ledger.append("stale", cid, via="audit")
        return {"audited": checked, "failed": failed, "E": self.auditor.error_rate}

    def status(self) -> dict:
        fresh = sum(1 for m in self.memory.values() if m.status == "fresh")
        stale = sum(1 for m in self.memory.values() if m.status == "stale")
        mem_tokens = sum(self.by_cid[c].tokens for c in self.memory if c in self.by_cid)
        return {
            "corpus": str(self.corpus),
            "chunks": len(self.chunks),
            "symbols": len(self.index),
            "memory_entries": len(self.memory),
            "fresh": fresh,
            "stale": stale,
            "memory_tokens": mem_tokens,
            "turns": len(self.history),
            "budget": self.budget,
            "guard_level": self.guard_level,
            "strict_visibility": self.strict_visibility,
            "tokenizer": TOKENIZER_NAME,
            "world_fp": self.world_fp,
            "gate_hits": self._gate_hits,
            "gate_misses": self._gate_misses,
            "gate_interval": self.gate_interval,
            "audited": self.auditor.audited,
            "E": self.auditor.error_rate,
            "ledger": self.ledger.summary(),
        }
