"""doctor：在采用 ctxfold 之前，先诊断这个仓库适不适合。

它回答四个问题：
  1. 这个仓库的规模与粒度（chunk 数、token 分布）是否适合符号级装配？
  2. 依赖密度如何？（出度越高，闭包越大，严格可见率损失越大——这是实测结论）
  3. 模拟一轮会话，能省多少 token、严格可见率损失多少？
  4. 建议用哪种配置（预算、是否开启 strict_visibility）？

不调用任何模型、不需要网络；输出人类可读结论 + 机器可读 JSON。
"""
from __future__ import annotations

import statistics as st
from dataclasses import dataclass
from pathlib import Path

from .assembler import Memory, assemble
from .chunker import load_corpus
from .tasks import build_tasks
from .tokenize import TOKENIZER_NAME, token_count


@dataclass
class Diagnosis:
    root: str
    files: int
    chunks: int
    tokens_median: int
    tokens_p75: int
    tokens_p95: int
    avg_out_degree: float
    cross_file_ratio: float
    orphan_ratio: float
    sim_turns: int
    full_tokens: int
    loose_tokens: int
    loose_r_prompt: float
    strict_tokens: int
    strict_r_prompt: float
    verdict: str
    suggested_budget: int
    suggested_strict: bool
    tokenizer: str

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}  # type: ignore[attr-defined]


def _simulate(tasks, by_cid, index, sha, budget, strict: bool):
    memory: dict[str, Memory] = {}
    history: list[str] = []
    total = 0
    rp = []
    ablate = frozenset({"placeholder"}) if strict else frozenset()
    for task in tasks:
        res = assemble("ours", task["query"], history, by_cid, index, memory, sha,
                       budget=budget, ablate=ablate)
        history.append(res.history_append)
        gold = set(task["gold"])
        rp.append(len(gold & set(res.included_cids)) / len(gold))
        total += token_count(res.prompt)
    return total, st.mean(rp)


def _simulate_full(tasks, by_cid):
    history: list[str] = []
    total = 0
    for task in tasks:
        text = by_cid[task["cid"]].text
        prompt = "\n\n".join(history + [text]) + f"\n\n[问题] {task['query']}"
        total += token_count(prompt)
        history.append(text)
    return total


def diagnose(root: Path, turns: int = 20, seed: int = 7, budget: int = 1600) -> Diagnosis:
    root = Path(root)
    chunks, index, sha = load_corpus(root)
    if not chunks:
        raise ValueError(f"没有找到可切的 Python 符号：{root}")

    by_cid = {c.cid: c for c in chunks}
    toks = sorted(c.tokens for c in chunks)
    deps = [len(c.__dict__.get("deps", [])) for c in chunks]
    cross = sum(
        1 for c in chunks for d in c.__dict__.get("deps", []) if by_cid[d].path != c.path
    )
    depended = {d for c in chunks for d in c.__dict__.get("deps", [])}
    orphans = sum(1 for c in chunks if not c.__dict__.get("deps") and c.cid not in depended)

    tasks = build_tasks(chunks, min(turns, max(5, len(chunks))), seed, locality=True, far_ref=0.4)
    if not tasks:
        raise ValueError(
            "可用符号太少（每个 chunk 需 ≥40 token）——这个仓库可能代码过碎，不适合符号级装配"
        )
    full = _simulate_full(tasks, by_cid)
    loose_t, loose_r = _simulate(tasks, by_cid, index, sha, budget, strict=False)
    strict_t, strict_r = _simulate(tasks, by_cid, index, sha, budget, strict=True)

    avg_out = sum(deps) / len(deps)
    saving = 1 - loose_t / full if full else 0.0
    loss = strict_r - loose_r   # 不用 strict 时损失的严格可见率

    # 先看绝对水平：可见率本身过低时，谈"损失小"没有意义
    if loose_r < 0.5:
        verdict = (f"默认配置下严格可见率只有 {loose_r:.1%}——这个仓库不适合直接用默认配置："
                   f"符号重名多/依赖密，命中会扩散成一堆占位符。"
                   f"建议：提高预算（当前 {budget}）或改用 --strict；否则请缩小 corpus 到子目录。")
        return_diagnosis_override = True
    else:
        return_diagnosis_override = False

    # 用模拟出来的真实损失做判断，而不是用出度之类的代理指标
    # （实测：本工程出度仅 1.09，但默认配置下严格可见率只有 0.463）
    if return_diagnosis_override:
        suggested_strict = True
    elif loss >= 0.25:
        verdict = (f"关闭 strict 会损失 {loss:.0%} 的严格可见率（占位符太多）。"
                   f"建议默认开 --strict；若坚持默认配置，必须确保模型会主动 recall。")
        suggested_strict = True
    elif loss >= 0.10:
        verdict = (f"中等损失（{loss:.0%}）：先用默认配置，观察到答错再切 --strict。")
        suggested_strict = False
    else:
        verdict = (f"损失很小（{loss:.0%}）：默认配置即可，卡片/占位符足够。")
        suggested_strict = False

    med = toks[len(toks) // 2]
    p75 = toks[int(0.75 * (len(toks) - 1))]
    return Diagnosis(
        root=str(root),
        files=len({c.path for c in chunks}),
        chunks=len(chunks),
        tokens_median=med,
        tokens_p75=p75,
        tokens_p95=toks[int(0.95 * (len(toks) - 1))],
        avg_out_degree=round(avg_out, 2),
        cross_file_ratio=round(cross / max(1, sum(deps)), 3),
        orphan_ratio=round(orphans / len(chunks), 3),
        sim_turns=len(tasks),
        full_tokens=full,
        loose_tokens=loose_t,
        loose_r_prompt=round(loose_r, 3),
        strict_tokens=strict_t,
        strict_r_prompt=round(strict_r, 3),
        verdict=verdict,
        suggested_budget=max(800, min(3200, p75 * 3)),
        suggested_strict=suggested_strict,
        tokenizer=TOKENIZER_NAME,
    )


def render(d: Diagnosis) -> str:
    saving = 1 - d.loose_tokens / d.full_tokens if d.full_tokens else 0
    if saving >= 0:
        save_txt = f"省 {saving:.0%}"
    else:
        # 小仓库上闭包 + 出处头可能比单轮全量更贵；照实说，不粉饰
        save_txt = f"不划算（多 {-saving:.0%}）"
    lines = [
        f"仓库: {d.root}",
        f"规模: {d.files} 文件 / {d.chunks} 个符号；token 中位 {d.tokens_median}，"
        f"p75 {d.tokens_p75}，p95 {d.tokens_p95}",
        f"依赖: 平均出度 {d.avg_out_degree}，跨文件边占比 {d.cross_file_ratio:.1%}，孤立符号 {d.orphan_ratio:.1%}",
        "",
        f"模拟 {d.sim_turns} 轮（局部性 + 40% 长程引用）：",
        f"  全量            {d.full_tokens:>9,} token",
        f"  默认配置        {d.loose_tokens:>9,} token   {save_txt}   严格可见率 {d.loose_r_prompt:.3f}",
        f"  --strict        {d.strict_tokens:>9,} token              严格可见率 {d.strict_r_prompt:.3f}",
        "",
        f"建议预算: {d.suggested_budget}  建议 --strict: {'是' if d.suggested_strict else '否'}",
        f"结论: {d.verdict}",
    ]
    if d.chunks < 20 or d.sim_turns < 5:
        lines.append(
            f"⚠ 仓库过小（{d.chunks} 个符号 / 模拟 {d.sim_turns} 轮）：本诊断不稳定，仅供参考。"
        )
    return "\n".join(lines)
