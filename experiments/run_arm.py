# -*- coding: utf-8 -*-
"""跑 m3 在线实验的一条臂：自己设好密钥与开关，再调 m3_online.main。

用法：python experiments/run_arm.py <arm-name> <boost:0|1> [任务数]
密钥只从 ~/.dsh/secrets/media-tools.env 读，不打印、不落盘。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC = Path.home() / ".dsh" / "secrets" / "media-tools.env"


def key() -> str:
    for line in SEC.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("SILICONFLOW_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no key")


def main() -> int:
    arm = sys.argv[1]
    boost = sys.argv[2] if len(sys.argv) > 2 else "1"
    tasks = sys.argv[3] if len(sys.argv) > 3 else "30"
    os.environ["CTXFOLD_BASE_URL"] = "https://api.siliconflow.cn/v1"
    os.environ["CTXFOLD_API_KEY"] = key()
    os.environ["CTXFOLD_MODEL"] = "deepseek-ai/DeepSeek-V3.2"
    os.environ["CTXFOLD_DEPS_BOOST"] = boost
    os.environ["PYTHONIOENCODING"] = "utf-8"
    print(f"[arm {arm}] boost={boost} tasks={tasks}", flush=True)
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "experiments"))
    import m3_online

    argv = ["--mode", "real",
            "--corpus", r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib\http",
            "--tasks", tasks, "--seed", "7", "--answerable-only", "--tag", arm]
    rc = m3_online.main.__wrapped__(argv) if hasattr(m3_online.main, "__wrapped__") else None
    if rc is None:
        # m3_online.main 用 argparse 读 sys.argv，这里直接替换
        sys.argv = ["m3_online"] + argv
        rc = m3_online.main()
    print(f"[arm {arm}] rc={rc}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
