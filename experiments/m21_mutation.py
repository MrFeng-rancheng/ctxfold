# -*- coding: utf-8 -*-
"""M21 v4：代码修改场景（每个场景 × 每个方法用全新仓库，失效在装配前统计）。

三处修正：
  1) 每 (场景, 方法) 都从标准库重新拷一份仓库，T1 前断言与原始文件逐字节一致；
  2) 失效统计在 mutate 之后、assemble 之前算（按哈希直接比），并把 stale 写回记忆；
  3) 指标拆三类：陈旧误用 / 证据不足猜错 / 改后答对。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold import llm  # noqa: E402
from ctxfold.assembler import assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.retrieve import BM25  # noqa: E402
from ctxfold.tokenize import token_count  # noqa: E402

STDLIB = Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")
BUDGET, MUTATE_TURN = 1600, 3
BAD = '"' + chr(92) + 'q"'


def replace_body(src: str, header: str, new_body: str) -> str:
    i = src.index(header)
    j = i + len(header)
    while j < len(src) and src[j] != "\n":
        j += 1
    j += 1
    k = j
    while k < len(src):
        e = src.find("\n", k)
        e = len(src) if e < 0 else e
        line = src[k:e]
        if line.strip() and not line.startswith((" ", "\t")):
            break
        if line.strip().startswith("def ") and line.startswith("    "):
            break
        k = e + 1
    return src[:j] + new_body + src[k:]


S1_MUT = lambda s: replace_body(s, "    def decode(self, s, _w=WHITESPACE.match):",
                                "        raise ValueError('m21')  # mutated\n")
S2_MUT = lambda s: replace_body(s, "    def encode(self, o):",
                                "        return b'{}'  # mutated\n")
S3_MUT = lambda s: replace_body(s, "    def raw_decode(self, s, idx=0):",
                                "        return (42, len(s))  # mutated\n")

SCEN = [
    {"name": "S1 改自身（decode 抛异常）", "file": "decoder.py",
     "ask": "JSONDecoder 的 decode 方法遇到非法转义时会抛出什么异常类型？只回答类名。",
     "probe": f"type((lambda: m.JSONDecoder().decode({BAD!r}))()).__name__",
     "mutate": S1_MUT, "extra_ask": "raw_decode 这个名字是否存在？只回答名字本身。"},
    {"name": "S2 改返回（encode 类型）", "file": "encoder.py",
     "ask": "JSONEncoder 的 encode 方法返回什么类型？只回答类型名。",
     "probe": "type(m.JSONEncoder().encode({'a': 1})).__name__",
     "mutate": S2_MUT, "extra_ask": "encode_basestring 这个名字是否存在？只回答名字本身。"},
    {"name": "S3 改下游（raw_decode 返回值）", "file": "decoder.py",
     "ask": "JSONDecoder 的 decode 方法正常解码后返回什么类型？只回答类型名。",
     "probe": "type(m.JSONDecoder().decode('{\"a\": 1}')).__name__",
     "mutate": S3_MUT, "extra_ask": "raw_decode 这个名字是否存在？只回答名字本身。"},
]


def probe(path: Path, expr: str) -> str:
    mod = types.ModuleType("probe_mod")
    mod.__dict__.update({"__file__": str(path), "__name__": "probe_mod"})
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), mod.__dict__)
        mod.__dict__["m"] = mod
        return repr(eval(expr, mod.__dict__))
    except Exception as e:
        return f"EXC {type(e).__name__}"


def truth(s: str) -> set[str]:
    ids = {t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", s)}
    return ids - {"exc"}


def fresh_repo() -> Path:
    d = Path(tempfile.mkdtemp(prefix="m21-"))
    for f in ("decoder.py", "encoder.py"):
        (d / f).write_bytes((STDLIB / "json" / f).read_bytes())
    return d


def pristine(repo: Path) -> bool:
    return all(hashlib.sha256((repo / f).read_bytes()).digest()
               == hashlib.sha256((STDLIB / "json" / f).read_bytes()).digest()
               for f in ("decoder.py", "encoder.py"))


def ask_model(prompt: str) -> str:
    resp = llm.chat([{"role": "system", "content": "只回答题目要求的那一项，不要解释、不要编号。"},
                     {"role": "user", "content": prompt}], max_tokens=96)
    return (resp["choices"][0]["message"].get("content") or "").strip()


def build_prompt(method, ask, history, by, bm25, memory, index, sha, snapshot):
    if method == "full":
        return f"{chr(10).join(snapshot.values())}\n\n[问题] {ask}", None
    if method == "window":
        body = list(snapshot.values())[0][: BUDGET * 4]
        return f"{body}\n\n[问题] {ask}", None
    if method == "summary":
        digest = "；".join(h[:80] for h in history[-6:]) or "（无）"
        return f"[历史摘要] {digest}\n\n[问题] {ask}", None
    if method == "grepriag":
        got = bm25.top_k(ask, k=4, budget=BUDGET)
        ev = "\n\n".join(f"### #{c.cid} | {c.path}:{c.start}-{c.end}\n{c.text}" for c in got)
        return f"[检索证据]\n{ev}\n\n[问题] {ask}", None
    res = assemble("ours", ask, history, by, index, memory, sha, budget=BUDGET)
    return res.prompt, res


def run_one(method: str, sc: dict, gold_pre: set, gold_post: set) -> dict:
    repo = fresh_repo()
    assert pristine(repo), "仓库起点被污染"
    snapshot = {str(p): p.read_text(encoding="utf-8") for p in (repo / sc["file"],)}
    chunks, index, sha = load_corpus(repo)
    by = {c.cid: c for c in chunks}
    bm25 = BM25(chunks)
    memory: dict = {}
    history: list[str] = []
    turns = []
    invalidated, downstream, kept = [], [], []
    for turn in range(1, 5):
        if turn == MUTATE_TURN:
            p = repo / sc["file"]
            p.write_text(sc["mutate"](p.read_text(encoding="utf-8")), encoding="utf-8")
            chunks, index, sha = load_corpus(repo)
            by = {c.cid: c for c in chunks}
            bm25 = BM25(chunks)
            # —— 失效统计：装配之前，按哈希直算 ——
            invalidated = [cid for cid, m in memory.items()
                           if cid in by and m.chunk_sha and m.chunk_sha != by[cid].text_sha]
            rev: dict[str, list[str]] = {}
            for cid, ck in by.items():
                for d in getattr(ck, "deps", []) or []:
                    rev.setdefault(d, []).append(cid)
            downstream = sorted({d for cid in invalidated for d in rev.get(cid, [])
                                 if d in memory and d not in invalidated})
            kept = sorted(c for c, m in memory.items()
                          if c not in invalidated and c not in downstream)
            for cid in invalidated + downstream:
                if cid in memory:
                    memory[cid].status = "stale"      # 让装配器真的重读
        ask = sc["ask"] if turn != 4 else sc["extra_ask"]
        prompt, res = build_prompt(method, ask, history, by, bm25, memory, index, sha, snapshot)
        ans = ask_model(prompt)
        history.append(res.history_append if res is not None else f"[问] {ask}\n[答] {ans}")
        got = truth(ans)
        turns.append({"turn": turn, "tokens": token_count(prompt), "answer": ans[:160],
                      "prompt": prompt[:700],
                      "hit_pre": bool(got & gold_pre), "hit_post": bool(got & gold_post)})
    t3 = turns[2]
    stale = bool(t3["hit_pre"] and not t3["hit_post"])
    wrong = bool(not t3["hit_pre"] and not t3["hit_post"])
    return {"method": method, "scenario": sc["name"], "tokens_total": sum(t["tokens"] for t in turns),
            "stale_misuse": stale, "wrong_guess": wrong, "correct_after": bool(t3["hit_post"]),
            "invalidated": invalidated, "downstream": downstream, "kept": kept, "turns": turns}


def main() -> int:
    methods = sys.argv[1].split(",") if len(sys.argv) > 1 else ["full", "window", "summary", "grepriag", "ours"]
    pick = os.environ.get("CTX_M21_SCEN", "")
    chosen = [x for x in SCEN if (not pick or x["name"][:2] in pick.split(","))]
    rows = []
    for sc in chosen:
        base = fresh_repo()
        gp = probe(base / sc["file"], sc["probe"])
        shadow = fresh_repo()
        p = shadow / sc["file"]
        p.write_text(sc["mutate"](p.read_text(encoding="utf-8")), encoding="utf-8")
        gq = probe(shadow / sc["file"], sc["probe"])
        assert gp != gq, f"{sc['name']} 探针无效：{gp} == {gq}"
        gold_pre, gold_post = truth(gp), truth(gq)
        print(f"[{sc['name']}] 改前={gp} 改后={gq}", flush=True)
        for m in methods:
            r = run_one(m, sc, gold_pre, gold_post)
            rows.append(r)
            tag = "陈旧" if r["stale_misuse"] else ("猜错" if r["wrong_guess"] else "答对")
            print(f"   {m:8s} tok={r['tokens_total']:6d} {tag} 失效={len(r['invalidated'])} "
                  f"波及={len(r['downstream'])} 保留={len(r['kept'])}", flush=True)
    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m21")
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(
        {"manifest": {"budget": BUDGET, "mutate_turn": MUTATE_TURN, "methods": methods,
                      "scenarios": [s["name"] for s in chosen]}, "rows": rows},
        ensure_ascii=False, indent=2), "utf-8")
    print("run dir:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
