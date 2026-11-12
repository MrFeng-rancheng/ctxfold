"""世界指纹：判断"世界有没有变"的廉价门。

两级设计（成本差三个数量级）：
  cheap   —— (路径, 大小, mtime) 的哈希。不读文件内容，毫秒可算。
             会**误报**（touch 一下、checkout 一下 mtime 就变），但不会漏报内容变化。
  content —— 逐个文件读内容做 sha256。准确，但要读全库。

用法：
  每轮先算 cheap；与上次相同 → 直接复用已有符号哈希，跳过 240 次文件读取。
  不同 → 再做 content 或逐符号校验，决定哪些结论真的失效。

注意：cheap 只用于**跳过**，绝不用于**判定失效**。误报的成本是"多算一次"，
漏报的成本是"用了错的结论"——所以宁可误报。
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path


def _iter_py(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name


def cheap_fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for p in _iter_py(root):
        try:
            st = p.stat()
        except OSError:
            continue
        h.update(f"{p.relative_to(root).as_posix()}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:16]


def content_fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for p in _iter_py(root):
        try:
            h.update(p.relative_to(root).as_posix().encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            continue
    return h.hexdigest()[:16]


def git_head(root: Path) -> str | None:
    """不依赖 git 命令：直接读 .git/HEAD（够用且零开销）。"""
    head = root / ".git" / "HEAD"
    ref = root / ".git" / "refs"
    try:
        txt = head.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if txt.startswith("ref: "):
        ref_path = root / ".git" / txt[5:]
        try:
            return ref_path.read_text(encoding="utf-8").strip()[:12]
        except OSError:
            return txt[5:]
    return txt[:12]


@dataclass
class Scope:
    root: Path
    cheap: str
    content: str
    head: str | None
    files: int
    ms_cheap: float
    ms_content: float

    def as_dict(self) -> dict:
        return {
            "root": str(self.root),
            "cheap": self.cheap,
            "content": self.content,
            "git_head": self.head,
            "files": self.files,
            "ms_cheap": round(self.ms_cheap, 2),
            "ms_content": round(self.ms_content, 2),
        }


def scope_fingerprint(root: Path) -> Scope:
    root = Path(root)
    t0 = time.perf_counter()
    cheap = cheap_fingerprint(root)
    t1 = time.perf_counter()
    content = content_fingerprint(root)
    t2 = time.perf_counter()
    files = sum(1 for _ in _iter_py(root))
    return Scope(root, cheap, content, git_head(root), files,
                 (t1 - t0) * 1000, (t2 - t1) * 1000)
