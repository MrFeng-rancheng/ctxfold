"""M4 世界指纹实验（离线）：廉价门到底省了多少，以及它的误报代价。

测三件事：
  1. cheap vs content 的耗时差；
  2. touch（mtime 变、内容不变）时 cheap 是否误报、content 是否稳定；
  3. 内容真变时两者是否都报。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.world import cheap_fingerprint, content_fingerprint, scope_fingerprint  # noqa: E402

CORPUS = Path(
    r"C:/Users/13956/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/Lib/http"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(CORPUS),
                    help="默认是 Lib/http（5 个文件）；想看规模效应可指向整个 Lib")
    ap.add_argument("--in-place", action="store_true", help="直接在被指向的目录上测（只读操作）")
    args = ap.parse_args()
    src = Path(args.corpus)
    if args.in_place:
        tmp = Path(tempfile.mkdtemp(prefix="ctxfold-world-"))
        repo = src
    else:
        tmp = Path(tempfile.mkdtemp(prefix="ctxfold-world-"))
        repo = tmp / "repo"
        shutil.copytree(src, repo)

    # 预热：排除首次目录遍历/文件系统缓存带来的假差距
    cheap_fingerprint(repo); content_fingerprint(repo)
    base = scope_fingerprint(repo)
    print(f"files={base.files}  cheap={base.ms_cheap}ms  content={base.ms_content}ms"
          f"  (content 是 cheap 的 {base.ms_content / max(base.ms_cheap, 1e-9):.0f}×)")

    # 1) touch：mtime 变、内容不变
    p = next(repo.glob("*.py"))
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    c2, k2 = cheap_fingerprint(repo), content_fingerprint(repo)
    print(f"touch 后：cheap 变化={c2 != base.cheap}（应为 True=误报）  "
          f"content 变化={k2 != base.content}（应为 False=正确）")

    # 2) 真改内容
    p.write_text(p.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    c3, k3 = cheap_fingerprint(repo), content_fingerprint(repo)
    print(f"改内容后：cheap 变化={c3 != c2}（应 True）           content 变化={k3 != k2}（应 True）")

    # 3) 重复算 N 次的成本（模拟每轮 gate）
    n = 20
    t0 = time.perf_counter()
    for _ in range(n):
        cheap_fingerprint(repo)
    t_cheap = (time.perf_counter() - t0) / n * 1000
    t0 = time.perf_counter()
    for _ in range(n):
        content_fingerprint(repo)
    t_content = (time.perf_counter() - t0) / n * 1000
    print(f"每轮成本：cheap {t_cheap:.1f}ms  content {t_content:.1f}ms  "
          f"（每轮省 {t_content - t_cheap:.1f}ms）")

    out = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m4-world")
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "manifest": {"corpus": str(src), "files": base.files, "n_repeat": n},
        "cheap_ms": round(t_cheap, 2),
        "content_ms": round(t_content, 2),
        "ratio": round(t_content / max(t_cheap, 1e-9), 1),
        "touch_false_positive_cheap": c2 != base.cheap,
        "touch_detected_by_content": k2 != base.content,
        "real_change_detected_cheap": c3 != c2,
        "real_change_detected_content": k3 != k2,
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(f"run dir: {out}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
