"""M3 在线实验：A（正确率）/ H（免算率）/ 真实 recall 行为。

两种模式：
  --mode mock   完美读者模拟（不需要网络）：给定"模型 recall 概率 p"和"有证据时答对概率 q"，
                推演端到端准确率与成本。**这是敏感性分析，不是实验数据**，输出必须带标签。
  --mode real   调用真实模型（OpenAI 兼容端点），需要环境变量：
                  CTXFOLD_BASE_URL / CTXFOLD_API_KEY / CTXFOLD_MODEL
                没有凭据时直接退出并给出提示，不伪造结果。

任务设计（答案可离线校验，不需要 judge 模型）：
  Q1 定位：符号 X 定义在哪个文件、哪几行  -> 校验 文件:起-止
  Q2 依赖：符号 X 直接调用了哪些函数      -> 校验 集合
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics as st
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold import llm  # noqa: E402
from ctxfold.assembler import Memory, assemble  # noqa: E402
from ctxfold.chunker import load_corpus  # noqa: E402
from ctxfold.tokenize import IS_ESTIMATE, TOKENIZER_NAME, token_count  # noqa: E402

DEFAULT_CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)


KINDS = ("q_locate", "q_deps", "q_exc")


def make_questions(by_cid, chunks, n, seed):
    rng = random.Random(seed)
    pool = [c for c in chunks if c.tokens >= 40]
    rng.shuffle(pool)
    out = []
    for c in pool[:n]:
        deps = [by_cid[d].name for d in c.__dict__.get("deps", []) if d in by_cid]
        raises = []
        for line in c.text.splitlines():
            t = line.strip()
            if t.startswith("raise "):
                name = t[6:].split("(")[0].split()[0].strip(",:")
                name = name.split(".")[-1]
                if name and name not in raises:
                    raises.append(name)
        out.append({
            "cid": c.cid,
            "q_exc": {
                "query": f"符号 {c.name} 会抛出哪些异常类型？只列异常类名，用英文逗号分隔；没有就回答 none。",
                "gold": set(raises),
                "need": {c.cid},
            },
            "q_locate": {
                "query": f"符号 {c.name} 定义在哪个文件、哪些行？只回答 文件名:起始行-结束行，不要解释。",
                "gold": f"{c.path}:{c.start}-{c.end}",
                "need": {c.cid},
            },
            "q_deps": {
                "query": f"符号 {c.name} 直接调用了哪些函数？只列函数名，用英文逗号分隔；没有就回答 none。",
                "gold": set(deps),
                "need": {c.cid},
            },
        })
    return out


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
STOP = {"none", "the", "and", "or", "no", "none.", "it", "returns", "raises"}


def _idents(text: str) -> set[str]:
    return {t.lower() for t in IDENT.findall(text) if t.lower() not in STOP}


def _match_span(ans: str, gold: str) -> bool:
    """定位题容错：既接受 `path:906-927`，也接受"文件 + 起止行号都在"。"""
    a = ans.replace(" ", "").replace("：", ":")
    g = gold.replace(" ", "")
    if g in a:
        return True
    path, rng = g.rsplit(":", 1)
    s, e = rng.split("-")
    if path.split("/")[-1] not in ans:
        return False
    nums = re.findall(r"\d+", ans)
    return s in nums and e in nums


def f1(ans: str, gold: set) -> float:
    """gold 是"仓库内可解析的被调用名"，是真实调用集的**子集**（内置函数不在其中）。
    因此对 deps 题用 F1 而不是集合相等，否则模型答对更多反而被判错。"""
    if not gold:
        return 1.0 if not _idents(ans) else 0.0
    got = _idents(ans)
    g = {x.lower() for x in gold}
    tp = len(got & g)
    if tp == 0:
        return 0.0
    p, r = tp / len(got), tp / len(g)
    return 2 * p * r / (p + r)


def check(ans: str, gold) -> bool:
    a = (ans or "").strip()
    if isinstance(gold, set):
        return _idents(a) == {g.lower() for g in gold}
    return _match_span(a, ans and gold)


def resolve_cid(by_cid, index, arg: str):
    """把模型给的 id 解析成真实 cid。返回 (cid|None, 错误提示|None)。

    模型经常给 `Class.method` 而不是 `path.py::Class.method`；这里做容错，
    解析不出来时返回候选列表，让模型有机会自己纠正——而不是直接喂 "(未找到)"。
    """
    a = (arg or "").strip().lstrip("#").strip()
    if a in by_cid:
        return a, None
    for key in (a, a.split("::")[-1].split(".")[-1]):
        cands = index.get(key, [])
        if len(cands) == 1:
            return cands[0], None
        if len(cands) > 1:
            exact = [c for c in cands if by_cid[c].name == key or by_cid[c].name.endswith("." + key)]
            if len(exact) == 1:
                return exact[0], None
            return None, "ambiguous id, candidates: " + ", ".join(cands[:6])
    return None, ("unknown id. 请从上下文中 '#' 之后原样复制完整 id，"
                  "例如 client.py::HTTPResponse.getheader")


REPO_IDENT_NAMES: set[str] = set()
GOLD_EMPTY_TASKS = {"n": 0}


def set_repo_idents(index: dict) -> None:
    """把索引里的符号名（小写）装进全局，供"仓库内口径"判分使用。"""
    global REPO_IDENT_NAMES
    REPO_IDENT_NAMES = {k.lower() for k in index}
    REPO_IDENT_NAMES |= {k.split(".")[-1].lower() for k in index}


def run_real(questions, by_cid, index, sha, budget, max_calls=3):
    set_repo_idents(index)
    memory: dict[str, Memory] = {}
    history: list[str] = []
    rows = []
    for task in questions:
        for kind in KINDS:
            q = task[kind]
            res = assemble("ours", q["query"], history, by_cid, index, memory, sha, budget=budget)
            history.append(res.history_append)
            messages = [
                {"role": "system", "content": "你是代码助手。若需要未加载的实现细节，调用 recall(id)。回答必须严格遵守题目要求的格式：只输出列表本身，用英文逗号分隔，不要解释、不要编号、不要复述上下文；为空就只输出 none。"},
                {"role": "user", "content": res.prompt},
            ]
            tokens = token_count(res.prompt)
            up = uc = 0
            recalls, recall_miss, answer, err = 0, 0, "", None
            for _ in range(max_calls):
                try:
                    resp = llm.chat(messages, tools=[llm.RECALL_TOOL])
                except RuntimeError as e:
                    err = str(e)
                    break
                msg = resp["choices"][0]["message"]
                usage = resp.get("usage", {}) or {}
                tokens += usage.get("total_tokens", 0) or 0
                up += usage.get("prompt_tokens", 0) or 0
                uc += usage.get("completion_tokens", 0) or 0
                calls = msg.get("tool_calls") or []
                if calls:
                    messages.append(msg)
                    for call in calls:
                        cid, why = resolve_cid(by_cid, index,
                                               json.loads(call["function"]["arguments"]).get("id", ""))
                        if cid is None:
                            body = f"[recall 失败] {why}"
                            recall_miss += 1
                        else:
                            body = by_cid[cid].text
                            tokens += token_count(body)
                        recalls += 1
                        messages.append({"role": "tool", "tool_call_id": call["id"], "content": body})
                    continue
                answer = msg.get("content") or ""
                break
            ok = check(answer, q["gold"])
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
                ok_repo, f1_repo = None, None
            rows.append({
                "kind": kind, "cid": task["cid"], "ok": ok, "tokens": tokens,
                "gold": sorted(q["gold"]) if isinstance(q["gold"], set) else q["gold"],
                "f1": (round(f1v, 4) if f1v is not None else None),
                "f1_repo": (round(f1_repo, 4) if kind == "q_deps" else None),
                "ok_repo": (bool(ok_repo) if kind == "q_deps" else None),
                "answer": (answer or "")[:400],
                "recalls": recalls, "error": err,
                "usage_prompt": up, "usage_completion": uc, "recall_miss": recall_miss,
                "no_recall_correct": bool(ok and recalls == 0),
            })
    return rows


def run_mock(questions, by_cid, index, sha, budget, recall_rates=(0.0, 0.25, 0.5, 0.75, 1.0),
             q_given_evidence=0.85, trials=3):
    """完美读者 + recall 概率假设下的推演。

    规则：若所需证据已在 prompt（原文）-> 以 q_given_evidence 答对；
          若只在占位符里 -> 以 recall_rate 概率发起 recall（成功即视为拿到证据）；
          既不在也无法 recall -> 答错。
    """
    out = {}
    for p in recall_rates:
        acc, tokens_all, by_kind_all = [], [], []
        for t in range(trials):
            rng = random.Random(hash((p, t)) % 10**6 + 7)
            memory: dict[str, Memory] = {}
            history: list[str] = []
            ok = 0
            ok_by = {k: 0 for k in KINDS}
            n_by = {k: 0 for k in KINDS}
            tok = 0
            for task in questions:
                for kind in KINDS:
                    q = task[kind]
                    res = assemble("ours", q["query"], history, by_cid, index, memory, sha, budget=budget)
                    history.append(res.history_append)
                    t0 = token_count(res.prompt)
                    have_raw = bool(q["need"] & set(res.included_cids))
                    # 摘要卡可直接回答"定位"与"依赖"两类问题（卡里就有 path:lines 与 calls）
                    have_card = bool(q["need"] & set(getattr(res, "card_cids", [])))
                    have_ph = bool(q["need"] & set(res.placeholder_cids))
                    cost = t0
                    card_ok = kind in ("q_locate", "q_deps")  # 语义题卡片不够，必须读正文
                    got = have_raw or (have_card and card_ok)
                    if not have_raw and have_ph and rng.random() < p:
                        got = True
                        cost += sum(by_cid[c].tokens for c in q["need"] & set(res.placeholder_cids))
                    if got and rng.random() < q_given_evidence:
                        ok += 1
                        ok_by[kind] += 1
                    n_by[kind] += 1
                    tok += cost
            acc.append(ok / sum(n_by.values()))
            by_kind = {k: ok_by[k] / max(1, n_by[k]) for k in KINDS}
            by_kind_all.append(by_kind)
            tokens_all.append(tok)
        out[p] = {
            "A": round(st.mean(acc), 4),
            "tokens": round(st.mean(tokens_all)),
            "A_by_kind": {k: round(st.mean(t[k] for t in by_kind_all), 3) for k in KINDS},
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--tasks", type=int, default=30)
    ap.add_argument("--budget", type=int, default=1600)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mode", choices=["mock", "real"], default="mock")
    ap.add_argument("--tag", default="", help="附加到 run 目录名")
    ap.add_argument("--answerable-only", action="store_true",
                    help="只保留依赖题 gold 非空的题（gold 为空的题按构造必错）")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"[FATAL] corpus not found: {corpus}")
        return 2

    chunks, index, sha = load_corpus(corpus)
    by_cid = {c.cid: c for c in chunks}
    questions = make_questions(by_cid, chunks, args.tasks * 2 if args.answerable_only else args.tasks, args.seed)
    if args.answerable_only:
        questions = [q for q in questions if q["q_deps"]["gold"]][: args.tasks]

    out = ROOT / "experiments" / "runs" / (
        datetime.now().strftime("%Y%m%d-%H%M%S") + f"-m3-{args.mode}" + (f"-{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)

    if args.mode == "real":
        if not llm.available():
            print("没有可用凭据。请设置：")
            print("  CTXFOLD_BASE_URL / CTXFOLD_API_KEY / CTXFOLD_MODEL")
            print("（本地 Ollama 示例：CTXFOLD_BASE_URL=http://localhost:11434/v1 CTXFOLD_MODEL=qwen2.5-coder:7b）")
            return 3
        rows = run_real(questions, by_cid, index, sha, args.budget)
        n = len(rows)
        by_kind = {}
        for r in rows:
            by_kind.setdefault(r["kind"], []).append(r)
        summary = {
            "manifest": {"mode": "real",
                         "base": llm.config()["base"], "model": llm.config()["model"],
                         "tasks": len(questions),
                         "tokenizer": TOKENIZER_NAME, "estimate": IS_ESTIMATE, "budget": args.budget},
            "A": round(sum(r["ok"] for r in rows) / n, 4),
            "H": round(sum(r["no_recall_correct"] for r in rows) / n, 4),
            "recall_rate": round(sum(1 for r in rows if r["recalls"] > 0) / n, 4),
            "tokens_mean": round(st.mean(r["tokens"] for r in rows), 1),
            "tokens_total": sum(r["tokens"] for r in rows),
            "usage_prompt_total": sum(r["usage_prompt"] for r in rows),
            "usage_completion_total": sum(r["usage_completion"] for r in rows),
            "A_by_kind": {k: round(sum(1 for r in v if r["ok"]) / len(v), 4)
                          for k, v in by_kind.items()},
            "f1_deps_mean": round(st.mean([r["f1"] for r in rows if r["f1"] is not None] or [0]), 4),
            "A_repo_deps": round(sum(1 for r in rows if r["kind"] == "q_deps" and r.get("ok_repo"))
                                 / max(1, sum(1 for r in rows if r["kind"] == "q_deps")), 4),
            "f1_repo_deps_mean": round(st.mean([r["f1_repo"] for r in rows
                                                if r["kind"] == "q_deps" and r.get("f1_repo") is not None] or [0]), 4),
            "deps_gold_empty": sum(1 for r in rows if r["kind"] == "q_deps" and not r["gold"]),
            "recall_by_kind": {k: round(sum(1 for r in v if r["recalls"] > 0) / len(v), 4)
                               for k, v in by_kind.items()},
            "recall_miss_total": sum(r["recall_miss"] for r in rows),
            "errors": [r["error"] for r in rows if r["error"]][:5],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        table = run_mock(questions, by_cid, index, sha, args.budget)
        summary = {
            "manifest": {"mode": "mock", "tasks": len(questions), "budget": args.budget,
                         "NOTE": "模拟推演，非真实实验数据；仅用于说明 recall 率对 A 的影响"},
            "sweep": {str(k): v for k, v in table.items()},
        }
        print("recall 概率 -> 端到端准确率 A / 总 token（模拟，非真实数据）")
        print(f"  {'p':<6}{'A':>7}{'locate':>9}{'deps':>8}{'exc(语义)':>11}{'tokens':>9}")
        for p, v in table.items():
            k = v["A_by_kind"]
            print(f"  {p:<6}{v['A']:>7.3f}{k['q_locate']:>9.3f}{k['q_deps']:>8.3f}"
                  f"{k['q_exc']:>11.3f}{v['tokens']:>9,}")

    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    if args.mode == "real":
        with (out / "rows.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    print(f"run dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
