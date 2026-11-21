# -*- coding: utf-8 -*-
"""M12 跨模型在线实验（并行版）。

两种用法：
  worker：python experiments/m12_models.py --model "标签=模型id" --corpus http --tasks 20 --out 目录
  driver：python experiments/m12_models.py --driver --tasks 20          # 起 5 个子进程并行
  agg：   python experiments/m12_models.py --agg 目录                  # 汇总成 RESULTS-m12.md
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import statistics as st
import subprocess
import sys
import traceback
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments"))

SEC = pathlib.Path(r"C:\Users\13956\.dsh\secrets\media-tools.env")
STDLIB = pathlib.Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")
CORPUS = {"http": STDLIB / "http", "json": STDLIB / "json"}
MODELS = [
    ("DeepSeek-V3.2", "deepseek-ai/DeepSeek-V3.2"),
    ("Qwen3.5-9B", "Qwen/Qwen3.5-9B"),
    ("Qwen3.6-27B", "Qwen/Qwen3.6-27B"),
    ("GLM-5.3-Flash", "zai-org/GLM-5.3-Flash"),
    ("Kimi-K2.7-Code", "moonshotai/Kimi-K2.7-Code"),
]


def load_key() -> str:
    for line in SEC.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("SILICONFLOW_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def worker(label: str, mid: str, corpus: str, tasks: int, outdir: pathlib.Path) -> int:
    os.environ["CTXFOLD_BASE_URL"] = "https://api.siliconflow.cn/v1"
    os.environ["CTXFOLD_API_KEY"] = load_key()
    os.environ["CTXFOLD_MODEL"] = mid
    from ctxfold.chunker import load_corpus
    import m3_online as m3

    chunks, index, sha = load_corpus(CORPUS[corpus])
    by_cid = {c.cid: c for c in chunks}
    questions = m3.make_questions(by_cid, chunks, tasks, 7)
    print(f"[{label}/{corpus}] chunks={len(chunks)} questions={len(questions)}", flush=True)
    try:
        res = m3.run_real(questions, by_cid, index, sha, 1600)
    except Exception as e:
        print(f"[{label}/{corpus}] FAIL {type(e).__name__}: {e}", flush=True)
        traceback.print_exc(limit=2)
        return 1
    n = len(res)
    bk: dict[str, list[int]] = {}
    for r in res:
        bk.setdefault(r["kind"], []).append(1 if r["ok"] else 0)
    row = {
        "corpus": corpus, "model": label, "model_id": mid, "n": n,
        "A": round(sum(r["ok"] for r in res) / n, 4),
        "H": round(sum(r["no_recall_correct"] for r in res) / n, 4),
        "recall_rate": round(sum(1 for r in res if r["recalls"] > 0) / n, 4),
        "tokens_mean": round(st.mean(r["tokens"] for r in res), 1),
        "A_by_kind": {k: round(sum(v) / len(v), 4) for k, v in bk.items()},
        "f1_deps": round(st.mean([r["f1"] for r in res if r["f1"] is not None] or [0]), 4),
    }
    (outdir / f"{corpus}__{label}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), "utf-8")
    print(f"[{label}/{corpus}] A={row['A']:.3f} H={row['H']:.3f} recall={row['recall_rate']:.3f} "
          f"tok={row['tokens_mean']:.0f}", flush=True)
    return 0


def driver(tasks: int) -> int:
    outdir = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m12")
    outdir.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    procs = []
    for corpus in ("http", "json"):
        for label, mid in MODELS:
            cmd = [py, str(ROOT / "experiments" / "m12_models.py"),
                   "--model", f"{label}={mid}", "--corpus", corpus,
                   "--tasks", str(tasks), "--out", str(outdir)]
            log = open(outdir / f"{corpus}__{label}.log", "w", encoding="utf-8")
            procs.append((label, corpus, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)))
            print(f"start {label}/{corpus}", flush=True)
    for label, corpus, p in procs:
        rc = p.wait()
        print(f"done {label}/{corpus} rc={rc}", flush=True)
    print("OUTDIR", outdir, flush=True)
    return 0


def agg(outdir: pathlib.Path) -> int:
    rows = []
    for f in sorted(outdir.glob("*.json")):
        if f.name == "summary.json":
            continue
        rows.append(json.loads(f.read_text(encoding="utf-8")))
    rows.sort(key=lambda r: (r["corpus"], -r["A"]))
    (outdir / "summary.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), "utf-8")
    lines = ["# m12 跨模型在线实验（自动生成，勿手改）", "",
             "题库与装配方式与正文一致，温度 0，每题独立装配；模型均为 OpenAI 兼容端点。", "",
             "| 语料 | 模型 | 题数 | 准确率 | 免算率 | 取回率 | 依赖 F1 | 每轮 token |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| %s | %s | %d | %.3f | %.3f | %.3f | %.3f | %.0f |" %
                     (r["corpus"], r["model"], r["n"], r["A"], r["H"], r["recall_rate"],
                      r["f1_deps"], r["tokens_mean"]))
    (ROOT / "experiments" / "RESULTS-m12.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="")
    ap.add_argument("--corpus", default="http")
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--out", default="")
    ap.add_argument("--driver", action="store_true")
    ap.add_argument("--agg", default="")
    a = ap.parse_args()

    if a.agg:
        return agg(pathlib.Path(a.agg))
    if a.driver:
        return driver(a.tasks)
    if not a.model:
        print("need --model or --driver or --agg")
        return 2
    label, mid = a.model.split("=", 1)
    outdir = pathlib.Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    return worker(label, mid, a.corpus, a.tasks, outdir)


if __name__ == "__main__":
    raise SystemExit(main())
