# -*- coding: utf-8 -*-
"""给 m3_online 加：依赖题的"仓库内标识符"口径 + boost 开关 + 同题对比输出。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m3_online.py")
s = P.read_text(encoding="utf-8")
LOG = []


def rep(old, new, tag):
    global s
    if old not in s:
        print("[MISS]", tag)
        return
    s = s.replace(old, new, 1)
    LOG.append(tag)


# 1) 行里补两个口径：只算"仓库内可解析标识符"的 F1 与严格相等
rep('''                "f1": (round(f1v, 4) if f1v is not None else None),''',
    '''                "f1": (round(f1v, 4) if f1v is not None else None),
                "f1_repo": (round(f1_repo, 4) if kind == "q_deps" else None),
                "ok_repo": (bool(ok_repo) if kind == "q_deps" else None),''', "row-fields")

# 2) 计算逻辑：只把"仓库里的符号名"算进答案集合
rep('''            ok = check(answer, q["gold"])
            f1v = f1(answer, q["gold"]) if kind == "q_deps" else None''',
    '''            ok = check(answer, q["gold"])
            f1v = f1(answer, q["gold"]) if kind == "q_deps" else None
            # 依赖题的"仓库内口径"：模型常把 len/keys/lower 这类内置名也报上来，
            # 而标准答案只收仓库内可解析的被调用名。这里只看仓库内标识符。
            repo_idents = {i for i in _idents(answer or "") if i in REPO_IDENT_NAMES}
            gold_l = {g.lower() for g in q["gold"]} if isinstance(q["gold"], set) else set()
            if kind == "q_deps":
                if not gold_l:
                    ok_repo = not repo_idents          # gold 为空时：不报仓库名才算对
                    f1_repo = 1.0 if ok_repo else 0.0
                else:
                    tp = len(repo_idents & gold_l)
                    p = tp / len(repo_idents) if repo_idents else 0.0
                    r = tp / len(gold_l)
                    f1_repo = (2 * p * r / (p + r)) if tp else 0.0
                    ok_repo = repo_idents == gold_l
            else:
                ok_repo, f1_repo = None, None''', "scoring")

# 3) 模块级：仓库内标识符集合（run_real 调用前注入）
rep('''def run_real(questions, by_cid, index, sha, budget, max_calls=3):''',
    '''REPO_IDENT_NAMES: set[str] = set()
GOLD_EMPTY_TASKS = {"n": 0}


def set_repo_idents(index: dict) -> None:
    """把索引里的符号名（小写）装进全局，供"仓库内口径"判分使用。"""
    global REPO_IDENT_NAMES
    REPO_IDENT_NAMES = {k.lower() for k in index}
    REPO_IDENT_NAMES |= {k.split(".")[-1].lower() for k in index}


def run_real(questions, by_cid, index, sha, budget, max_calls=3):
    set_repo_idents(index)''', "repo-idents")

# 4) 汇总里加上新口径
rep('''            "f1_deps_mean": round(st.mean([r["f1"] for r in rows if r["f1"] is not None] or [0]), 4),''',
    '''            "f1_deps_mean": round(st.mean([r["f1"] for r in rows if r["f1"] is not None] or [0]), 4),
            "A_repo_deps": round(sum(1 for r in rows if r["kind"] == "q_deps" and r.get("ok_repo"))
                                 / max(1, sum(1 for r in rows if r["kind"] == "q_deps")), 4),
            "f1_repo_deps_mean": round(st.mean([r["f1_repo"] for r in rows
                                                if r["kind"] == "q_deps" and r.get("f1_repo") is not None] or [0]), 4),
            "deps_gold_empty": sum(1 for r in rows if r["kind"] == "q_deps" and not r["gold"]),''', "summary")

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("patched m3_online:", ", ".join(LOG))

# 5) assembler：boost 开关（默认开，可关掉做 A/B）
Q = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\src\ctxfold\assembler.py")
t = Q.read_text(encoding="utf-8")
old = '    deps_intent = bool(re.search(r"调用|calls|callee", query, re.I))'
new = ('    import os as _os\n'
       '    _boost = _os.environ.get("CTXFOLD_DEPS_BOOST", "1") not in ("0", "false", "False")\n'
       '    deps_intent = _boost and bool(re.search(r"调用|calls|callee", query, re.I))')
if old in t:
    t = t.replace(old, new, 1)
    Q.write_text(t, encoding="utf-8")
    ast.parse(t)
    print("patched assembler: boost switch")
else:
    print("[MISS] boost switch")
