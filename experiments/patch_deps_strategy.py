# -*- coding: utf-8 -*-
"""依赖题的装配策略改动：卡片区分 repo/ext 调用名；依赖类查询把被调用项提升为卡片。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\src\ctxfold\assembler.py")
s = P.read_text(encoding="utf-8")
LOG = []


def rep(old, new, tag):
    global s
    if old not in s:
        print("[MISS]", tag)
        return
    s = s.replace(old, new, 1)
    LOG.append(tag)


# 1) 识别"依赖类"查询，并收集被测符号的直接被调用项
rep('''    decisions.append(
        f"hits={len(hit_cids)} closure={len(closure)} hops={hops}"
        + (f" ablate={sorted(ablate)}" if ablate else "")
    )''',
    '''    decisions.append(
        f"hits={len(hit_cids)} closure={len(closure)} hops={hops}"
        + (f" ablate={sorted(ablate)}" if ablate else "")
    )

    # 依赖类查询：问"直接调用了哪些函数"时，把命中符号的直接被调用项
    # 从"纯 ID 占位符"提升为摘要卡（卡里带 calls(repo) 列表），
    # 否则模型只看到一个 id，答不出完整的被调用名集合。
    deps_intent = bool(re.search(r"调用|calls|callee", query, re.I))
    callee_cids: set[str] = set()
    if deps_intent:
        for cid in hit_cids:
            for d in getattr(chunks_by_cid[cid], "deps", []) or []:
                if d in chunks_by_cid:
                    callee_cids.add(d)
    if deps_intent:
        decisions.append(f"deps_intent=1 callees={len(callee_cids)}")''', "intent")

# 2) 记忆命中时：被调用项给卡片，而不是占位符
rep('''            elif cid in primary and "card" not in ablate:
                card_ids.append(cid)       # 否则退一步给摘要卡
            else:
                ph_ids.append(cid)''',
    '''            elif cid in primary and "card" not in ablate:
                card_ids.append(cid)       # 否则退一步给摘要卡
            elif cid in callee_cids and "card" not in ablate:
                card_ids.append(cid)       # 依赖题：被调用项给卡片（带 calls 列表）
            else:
                ph_ids.append(cid)''', "promote-mem")

# 3) 超预算时：被调用项也降级到卡片，而不是只剩 id
rep('''        if spent + ck.tokens > budget and include_raw:
            unloaded.append(cid)  # 降级为"未加载占位符"，仍可 recall（M0 诊断修正）
            continue''',
    '''        if spent + ck.tokens > budget and include_raw:
            if cid in callee_cids and "card" not in ablate:
                card_ids.append(cid)   # 依赖题：装不下原文就给卡片（名字仍在）
            else:
                unloaded.append(cid)   # 降级为"未加载占位符"，仍可 recall（M0 诊断修正）
            continue''', "promote-budget")

# 4) 卡片按需给全量调用名，并区分 repo / ext
rep('        parts.append(_cards(chunks_by_cid, card_ids))',
    '        parts.append(_cards(chunks_by_cid, card_ids, full_calls=deps_intent,\n'
    '                            repo_names=set(index)))', "cards-args")

# 5) 依赖题加一行答题提示（不改问题本身）
rep('    parts.append(f"[问题] {query}")',
    '''    if deps_intent and card_ids:
        parts.append("[答题提示] 问“直接调用了哪些函数”时，只列 calls(repo) 里的名字，用英文逗号分隔。")
    parts.append(f"[问题] {query}")''', "hint")

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("patched:", ", ".join(LOG))
