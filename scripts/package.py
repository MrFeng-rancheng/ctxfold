"""package：生成可上传的发布包（zip），并输出文件清单与校验和。

排除：.git、__pycache__、experiments/runs、.secrets.env、*.pyc、dist 自身。
用法：python scripts/package.py [--out dist]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {".git", "__pycache__", "runs", "dist", ".ctxfold", ".idea", ".vscode"}
EXCLUDE_FILES = {".secrets.env"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip"}


def collect() -> list[Path]:
    out: list[Path] = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.name in EXCLUDE_FILES or p.suffix in EXCLUDE_SUFFIXES:
            continue
        out.append(rel)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()

    files = collect()
    # 安全检查：绝不允许凭据或原始 run 进入发布包
    leaks = [f for f in files if f.name == ".secrets.env" or f.parts[0] == ".git"]
    if leaks:
        print(f"[FATAL] 包内含敏感/无关文件：{leaks[:5]}")
        return 1

    outdir = ROOT / args.out
    outdir.mkdir(exist_ok=True)
    version = "0.1.0"
    zip_path = outdir / f"ctxfold-{version}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(ROOT / rel, arcname=f"ctxfold-{version}/{rel.as_posix()}")

    data = zip_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    manifest = {
        "package": zip_path.name,
        "bytes": len(data),
        "sha256": sha,
        "files": len(files),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "top_level": sorted({f.parts[0] for f in files}),
        "entries": [f.as_posix() for f in files],
    }
    (outdir / f"ctxfold-{version}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
    )
    (outdir / f"ctxfold-{version}.sha256").write_text(f"{sha}  {zip_path.name}\n", "utf-8")

    print(f"包: {zip_path}")
    print(f"文件数: {len(files)}   大小: {len(data)/1024:.1f} KiB")
    print(f"sha256: {sha}")
    print(f"顶层目录: {', '.join(manifest['top_level'])}")
    print("已排除: .git / __pycache__ / experiments/runs / .secrets.env / *.pyc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
