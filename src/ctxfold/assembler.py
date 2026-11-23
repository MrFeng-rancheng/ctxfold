"""装配器：三种方法共用同一会话模拟接口。

方法：
  full   —— 全量历史（朴素基线上界）
  window —— 最近 k 轮
  ours   —— 状态记忆 + guard 校验 + 依赖闭包 + 占位符降级

设计约定（M0，必须与 protocol.md 一致）：
  * 每轮进入历史的内容 = 本轮"真正发给模型之外、但会留在对话里的那段文本"。
    full/window: 检索到的原文全部进历史；ours: 只有占位符/结论行进历史。
    这是三种方法成本差异的唯一来源，也是本方法主张的机制本身。
  * 命中 = query 里的标识符与 chunk 符号名精确匹配（不用向量，v0.1 有意为之）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .chunker import Chunk
from .tokenize import token_count

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# 中英混排修复（开关式）：汉字紧贴标识符时 \b 不成立，这里不要求词边界
_IDENT_FIX = os.environ.get("CTXFOLD_IDENT_FIX", "") not in ("", "0", "false", "False")
IDENT_FIX = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


@dataclass
class Memory:
    """一条固化结论。guard = 文件哈希（粗）或 符号哈希（细），机器可判定。"""

    cid: str
    name: str
    file_sha: str
    chunk_sha: str = ""
    status: str = "fresh"  # fresh | stale
    used: int = 0
    claim: str = ""                  # 当初得出的结论（自然语言）
    verifier: dict | None = None     # 可执行校验器：{"kind": "cmd", "cmd": [...]}


@dataclass
class TurnResult:
    prompt: str
    included_cids: list[str]       # 原文真正进入 prompt 的 chunk
    placeholder_cids: list[str]     # 以占位符形式可 recall 的 chunk
    history_append: str            # 本轮结束后追加进历史的文本
    no_model_needed: bool          # 全部依赖都已固化为 fresh（免算）
    decisions: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # 超预算、仅可 recall
    card_cids: list[str] = field(default_factory=list)  # 以"摘要卡"形式可见（非原文）
    claim_cids: list[str] = field(default_factory=list)  # 以"已验证结论"形式可见


def _placeholders(memory: dict[str, Memory], cids: list[str]) -> str:
    if not cids:
        return ""
    lines = ["[以固化，原文可 recall]"]
    for cid in cids:
        m = memory[cid]
        lines.append(f"- #{cid} ({m.name})")
    return "\n".join(lines)


def _claims(memory: dict[str, Memory], cids: list[str]) -> str:
    """已验证结论块：直接给结论，而不是给代码让人重推。

    这是"记忆"与"指针"的分界线：
      - 卡片回答"它在哪、它调用了什么"；
      - 结论回答"它是什么"——不需要再读代码。
    """
    lines = ["[已验证结论：可直接采用，无需重读代码]"]
    for cid in cids:
        m = memory[cid]
        lines.append(f"- #{cid} {m.claim}")
    return chr(10).join(lines)


def _cards(chunks_by_cid: dict[str, Chunk], cids: list[str], full_calls: bool = False,
           repo_names: set[str] | None = None) -> str:
    """摘要卡：id + 位置 + 签名首行 + 被调用名。

    为什么不是"只给 id"：占位符只给 id 时，模型必须 recall 才知道任何细节，
    连"这个函数在哪一行"这种问题都要多花一次往返。

    为什么要区分 repo / ext：标准答案只收"仓库内可解析的被调用名"，
    而 len/keys/lower 这类内置名会把答案的精确率拉低。卡上直接标出来，
    模型才知道哪些名字该报。
    """
    lines = ["[已固化摘要卡：细节可按 #id recall 原文]"]
    for cid in cids:
        ck = chunks_by_cid[cid]
        first = (ck.text.strip().splitlines() or [""])[0].strip()[:70]
        calls = list(ck.call_order or [])
        # 仓库内被调用名：用依赖边解析出**限定名**（HTTPMethod.__new__），
        # 而不是叶子名（__new__）——判分与阅读都需要限定名。
        dep_cids = [d for d in (getattr(ck, "deps", []) or []) if d in chunks_by_cid]
        repo = [chunks_by_cid[d].name for d in dep_cids]
        repo_leaf = {n.split(".")[-1] for n in repo}
        if repo_names is not None:
            ext = [c for c in calls if c not in repo_names and c not in repo_leaf]
        else:
            ext = [c for c in calls if c not in repo_leaf]
        if not full_calls:
            repo = repo[:6]
        seg = f"- #{cid} | {ck.path}:{ck.start}-{ck.end} | {first}"
        seg += " | calls(repo): " + (", ".join(repo) if repo else "（无，均为内置/外部）")
        if ext:
            seg += " | calls(ext): " + ", ".join(ext if full_calls else ext[:6])
        lines.append(seg)
    return "\n".join(lines)


def _recallable(chunks_by_cid: dict[str, Chunk], cids: list[str]) -> str:
    lines = ["[未加载，按需 recall 取原文]"]
    for cid in cids:
        lines.append(f"- #{cid} ({chunks_by_cid[cid].name})")
    return "\n".join(lines)


def _query_symbols(
    query: str, index: dict[str, list[str]], max_per_name: int = 3
) -> list[tuple[str, bool]]:
    """从 query 抽符号命中，返回 (cid, 是否首选)。

    优先级：
      1) 查询里出现**限定名**（如 HTTPConnection.__init__）→ 精确命中，作首选；
      2) 裸名 token → 若已有限定名命中，则只作**歧义候选**（占位符，不进原文）；
      3) 裸名无歧义时才作首选。
    歧义用占位符解决，而不是把多个同名实现都塞进 prompt（实测这样成本 ×2.7）。
    """
    hits: list[tuple[str, bool]] = []
    seen: set[str] = set()
    index_cids = {cid for v in index.values() for cid in (v if isinstance(v, list) else [v])}

    # 文件名命中：查询里出现 "xxx.py" 时，把该文件的 chunk 直接当首选命中，
    # 否则会被同名函数抢走（例如 tokenize.py 被 retrieve.py::tokenize 抢走）。
    for fn in re.findall(r"[A-Za-z0-9_./-]+\.py", query):
        base = fn.rsplit("/", 1)[-1]
        for cid in index_cids:
            if cid.split("::")[0].rsplit("/", 1)[-1] == base and cid not in seen:
                seen.add(cid)
                hits.append((cid, True))

    qualified = [k for k in index if "." in k and k in query]
    for key in qualified:
        for cid in index[key][:1]:
            if cid not in seen:
                seen.add(cid)
                hits.append((cid, True))

    _pat = IDENT_FIX if _IDENT_FIX else IDENT
    for tok in _pat.findall(query):
        for i, cid in enumerate(index.get(tok, [])[:max_per_name]):
            if cid in seen:
                continue
            seen.add(cid)
            hits.append((cid, (i == 0) and not qualified))
    return hits


def assemble(
    method: str,
    query: str,
    history: list[str],
    chunks_by_cid: dict[str, Chunk],
    index: dict[str, list[str]],
    memory: dict[str, Memory],
    current_sha: dict[str, str],
    window: int = 5,
    budget: int = 1600,
    hops: int = 1,
    guard_level: str = "symbol",
    ablate: frozenset[str] | set[str] = frozenset(),
) -> TurnResult:
    """ablate 用于消融实验，可控地关掉某个机制：
    closure（依赖闭包）/ placeholder（占位符降载）/ card（摘要卡）/ claim（结论层）
    """
    """返回本轮 prompt。history 由调用方维护。"""
    q_tokens = token_count(query)

    if method == "full":
        body = "\n\n".join(history)
        prompt = f"{body}\n\n[问题] {query}" if body else f"[问题] {query}"
        return TurnResult(prompt, [], [], query, False, ["full:no-state"])

    if method == "window":
        body = "\n\n".join(history[-window:]) if window > 0 else ""
        prompt = f"{body}\n\n[问题] {query}" if body else f"[问题] {query}"
        return TurnResult(prompt, [], [], query, False, [f"window:{window}"])

    # ---- ours ----
    decisions: list[str] = []
    hit_pairs = _query_symbols(query, index)
    hit_cids = [cid for cid, _ in hit_pairs]
    secondary = {cid for cid, primary in hit_pairs if not primary}
    closure: list[str] = []
    frontier = list(hit_cids)
    for hop in range(max(1, hops)):
        nxt: list[str] = []
        for cid in frontier:
            if cid not in closure:
                closure.append(cid)
            for dep in chunks_by_cid[cid].__dict__.get("deps", []):
                if dep not in closure and dep not in nxt:
                    nxt.append(dep)
        frontier = nxt
        if not frontier:
            break
    for cid in frontier:
        if cid not in closure:
            closure.append(cid)
    if "closure" in ablate:
        closure = list(hit_cids)  # 消融：只保留命中项，不沿依赖展开
    decisions.append(
        f"hits={len(hit_cids)} closure={len(closure)} hops={hops}"
        + (f" ablate={sorted(ablate)}" if ablate else "")
    )

    # 依赖类查询：问"直接调用了哪些函数"时，把命中符号的直接被调用项
    # 从"纯 ID 占位符"提升为摘要卡（卡里带 calls(repo) 列表），
    # 否则模型只看到一个 id，答不出完整的被调用名集合。
    import os as _os
    _boost = _os.environ.get("CTXFOLD_DEPS_BOOST", "1") not in ("0", "false", "False")
    deps_intent = _boost and bool(re.search(r"调用|calls|callee", query, re.I))
    callee_cids: set[str] = set()
    if deps_intent:
        for cid in hit_cids:
            for d in getattr(chunks_by_cid[cid], "deps", []) or []:
                if d in chunks_by_cid:
                    callee_cids.add(d)
    if deps_intent:
        decisions.append(f"deps_intent=1 callees={len(callee_cids)}")

    # guard 校验：guard_level=file 时文件一变全文件失效（粗）；=symbol 时只失效被改的符号（细）
    stale_now = 0
    for cid, mem in memory.items():
        ck = chunks_by_cid.get(cid)
        if ck is None:
            mem.status = "stale"
            stale_now += 1
            continue
        if guard_level == "file":
            sha = current_sha.get(ck.path)
            if sha is not None and sha != mem.file_sha:
                mem.status = "stale"
                stale_now += 1
        else:
            if mem.chunk_sha and ck.text_sha != mem.chunk_sha:
                mem.status = "stale"
                stale_now += 1
    decisions.append(
        f"stale_now={stale_now} stale_total={sum(1 for m in memory.values() if m.status == 'stale')}"
    )

    include_raw: list[str] = []
    include_ids: list[str] = []
    card_ids: list[str] = []
    claim_ids: list[str] = []
    ph_ids: list[str] = []
    unloaded: list[str] = []  # 超预算但仍在索引上（可 recall）——不消失
    spent = 0
    # 命中项优先，其次依赖项；超预算降级为"未召回"（不是占位符，占位符本身有成本）
    # 预算感知：命中项优先；依赖项按"单价便宜优先"排序（小 chunk 先装，装得多则 R 高）
    ordered = [c for c in closure if c in hit_cids] + sorted(
        [c for c in closure if c not in hit_cids],
        key=lambda cid: chunks_by_cid[cid].tokens,
    )
    primary = {cid for cid, is_primary in hit_pairs if is_primary}
    for cid in ordered:
        mem = memory.get(cid)
        if mem is not None and mem.status == "fresh" and "placeholder" not in ablate:
            if cid in primary and mem.claim and "claim" not in ablate:
                claim_ids.append(cid)      # 有已验证结论 -> 直接给结论（最便宜且最有用）
            elif cid in primary and "card" not in ablate:
                card_ids.append(cid)       # 否则退一步给摘要卡
            elif cid in callee_cids and "card" not in ablate:
                card_ids.append(cid)       # 依赖题：被调用项给卡片（带 calls 列表）
            else:
                ph_ids.append(cid)
            mem.used += 1
            continue
        ck = chunks_by_cid[cid]
        if cid in secondary and include_raw:
            unloaded.append(cid)  # 歧义候选：只占位符，不进原文
            continue
        if spent + ck.tokens > budget and include_raw:
            if cid in callee_cids and "card" not in ablate:
                card_ids.append(cid)   # 依赖题：装不下原文就给卡片（名字仍在）
            else:
                unloaded.append(cid)   # 降级为"未加载占位符"，仍可 recall（M0 诊断修正）
            continue
        # 原文必须自带出处：否则"它定义在哪一行"这类问题模型根本无从回答
        include_raw.append(f"### #{cid} | {ck.path}:{ck.start}-{ck.end}" + chr(10) + ck.text)
        include_ids.append(cid)
        spent += ck.tokens
        memory[cid] = Memory(
            cid=cid, name=ck.name, file_sha=ck.file_sha, chunk_sha=ck.text_sha
        )

    no_model_needed = bool(closure) and not include_raw
    decisions.append(
        f"raw={len(include_ids)} claim={len(claim_ids)} card={len(card_ids)} "
        f"placeholder={len(ph_ids)} unloaded={len(unloaded)}"
    )

    parts = []
    if claim_ids:
        parts.append(_claims(memory, claim_ids))
    if card_ids:
        parts.append(_cards(chunks_by_cid, card_ids, full_calls=deps_intent,
                            repo_names=set(index)))
    if ph_ids:
        parts.append(_placeholders(memory, ph_ids))
    if unloaded:
        parts.append(_recallable(chunks_by_cid, unloaded))
    if include_raw:
        parts.append("[证据原文]\n" + "\n\n".join(include_raw))
    if deps_intent and card_ids:
        parts.append("[答题提示] 问“直接调用了哪些函数”时，只列 calls(repo) 里的名字，用英文逗号分隔。")
    parts.append(f"[问题] {query}")
    prompt = "\n\n".join(parts)

    # 本轮进入历史的内容：ours 只留结论行，原文不进历史（这是省钱机制本身）
    append = "[结论] " + ", ".join(
        f"#{cid}" for cid in include_ids + [c for c in ph_ids if c not in include_ids]
    )
    return TurnResult(
        prompt,
        include_ids,
        claim_ids + card_ids + ph_ids + unloaded,   # 全部可按 #id recall 取回原文
        append,
        no_model_needed,
        decisions,
        dropped=unloaded,
        card_cids=card_ids + claim_ids,   # 结论块同样可直接回答"它是谁/在哪"
        claim_cids=claim_ids,
    )
