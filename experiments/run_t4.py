# -*- coding: utf-8 -*-
"""跑表 4（在线 150 题）的一个语料：与论文同口径，不筛题。

用法：python experiments/run_t4.py <tag> <corpus名> <题数>
语料名：http / json / unittest / this-repo
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC = Path.home() / ".dsh" / "secrets" / "media-tools.env"
STDLIB = Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")
CORPORA = {
    "http": STDLIB / "http",
    "json": STDLIB / "json",
    "unittest": STDLIB / "unittest",
    "this-repo": ROOT / "src",
}


def key() -> str:
    for line in SEC.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("SILICONFLOW_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no key")


def main() -> int:
    tag, corpus, n = sys.argv[1], sys.argv[2], sys.argv[3]
    os.environ["CTXFOLD_BASE_URL"] = "https://api.siliconflow.cn/v1"
    os.environ["CTXFOLD_API_KEY"] = key()
    os.environ["CTXFOLD_MODEL"] = "deepseek-ai/DeepSeek-V3.2"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "experiments"))
    import m3_online

    print(f"[t4 {tag}] corpus={corpus} tasks={n}", flush=True)
    sys.argv = ["m3_online", "--mode", "real", "--corpus", str(CORPORA[corpus]),
                "--tasks", n, "--seed", "7", "--tag", tag]
    rc = m3_online.main()
    print(f"[t4 {tag}] rc={rc}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
