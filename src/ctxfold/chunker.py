"""切块：文件 -> 符号级 chunk（函数/类/方法），带行号区间、文件哈希、调用名。

v0.1 只做符号级，不做 token 级滑动窗口：
代码域里"证据"的自然粒度就是一个可执行单元，符号级天然可解释、可校验。
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from .tokenize import token_count


@dataclass
class Chunk:
    cid: str
    path: str          # 相对仓库根的 posix 路径
    name: str          # 符号名（方法为 Class.method）
    kind: str          # function | method | class
    start: int         # 1-based 闭区间
    end: int
    text: str
    tokens: int
    file_sha: str
    calls: set[str] = field(default_factory=set)
    call_order: list[str] = field(default_factory=list)  # 按出现顺序，避免字母序偏置

    @property
    def span(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"

    @property
    def text_sha(self) -> str:
        """符号级指纹：只反映这个 chunk 自身的文本，用作细粒度 guard。"""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


def _collect_calls(node: ast.AST) -> list[str]:
    """按源码出现顺序收集被调用名（去重）。顺序很重要：决定依赖优先级。"""
    names: list[str] = []
    seen: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            n = None
            if isinstance(fn, ast.Name):
                n = fn.id
            elif isinstance(fn, ast.Attribute):
                n = fn.attr
            if n and n not in seen:
                seen.add(n)
                names.append(n)
    return names


def chunk_file(path: Path, root: Path) -> list[Chunk]:
    raw = path.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()[:16]
    try:
        source = raw.decode("utf-8")
        tree = ast.parse(source)
    except (UnicodeDecodeError, SyntaxError):
        return []

    lines = source.splitlines()
    rel = path.relative_to(root).as_posix()
    out: list[Chunk] = []
    seen: dict[str, int] = {}

    def emit(name: str, kind: str, node: ast.AST) -> None:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if not start or not end:
            return
        text = "\n".join(lines[start - 1 : end])
        if not text.strip():
            return
        base = name
        if name in seen:  # 同名重载/重复定义：追加序号保证 cid 唯一
            seen[name] += 1
            name = f"{name}#{seen[name]}"
        else:
            seen[base] = 1
        out.append(
            Chunk(
                cid=f"{rel}::{name}",
                path=rel,
                name=name,
                kind=kind,
                start=start,
                end=end,
                text=text,
                tokens=token_count(text),
                file_sha=file_sha,
                calls=set(_collect_calls(node)),
                call_order=_collect_calls(node),
            )
        )

    def visit(node, prefix: str = "") -> None:
        """只切"叶子"：模块级函数与类内方法。

        两条不变量：
          1) 方法用限定名 Class.method —— 消除 __init__/read 之类同名遮蔽；
          2) 不切类整块、不切嵌套函数 —— 否则父块已包含子块源码，同一段文本被重复计数，
             会把所有成本指标虚高（实测可虚高 46%）。
        """
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                emit(prefix + child.name, "method" if prefix else "function", child)
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")

    visit(tree)
    return out


# 默认跳过：这些目录里的 .py 通常是生成的、第三方的，或实验时复制进来的语料
DEFAULT_EXCLUDES = (
    "__pycache__", "node_modules", ".git", ".venv", "venv",
    "dist", "build", "site-packages", ".tox", ".mypy_cache",
)


def chunk_repo(root: Path, pattern: str = "**/*.py") -> list[Chunk]:
    """切仓库。

    默认排除 vendor/生成目录，以及 **experiments/runs/**（实验产物里常含复制的语料副本，
    直接扫进来会让符号数虚高十几倍、同名冲突爆掉，实测把 R 从 0.6 打到 0.03）。
    """
    chunks: list[Chunk] = []
    for p in sorted(root.glob(pattern)):
        if not p.is_file():
            continue
        # 用**相对**路径判断排除项：否则仓库本身被拷到 .../experiments/runs/ 下时
        # 会把整个语料当成实验产物排除掉（实测切出 0 个符号，实验静默退化）
        try:
            parts = p.relative_to(root).parts
        except ValueError:
            parts = p.parts
        if any(x in parts for x in DEFAULT_EXCLUDES):
            continue
        if "experiments" in parts and "runs" in parts:
            continue
        chunks.extend(chunk_file(p, root))
    return chunks


def build_symbol_index(chunks: list[Chunk]) -> dict[str, list[str]]:
    """裸符号名 -> 所有同名 cid（有序）。

    必须保留全部候选：代码域里 __init__ / read / close 这类名字大量重名，
    只留首个会让检索**系统性地指错对象**（实测 Lib/http 上 13.7% 的符号被遮蔽）。
    """
    idx: dict[str, list[str]] = {}
    for c in chunks:
        bare = c.name.split(".")[-1].split("#")[0]
        idx.setdefault(bare, []).append(c.cid)
        if "." in c.name:  # 同时收录限定名，供"查询里点名"时精确命中
            idx.setdefault(c.name, []).append(c.cid)
    return idx


def collect_imports(root: Path) -> dict[str, dict[str, str]]:
    """每个文件的名字 -> 被导入的模块路径（用于跨文件依赖解析）。"""
    out: dict[str, dict[str, str]] = {}
    for p in sorted(root.glob("**/*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_bytes().decode("utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            continue
        m: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    m[a.asname or a.name.split(".")[0]] = a.name
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                for a in node.names:
                    m[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
        out[p.relative_to(root).as_posix()] = m
    return out


def module_file_map(root: Path) -> dict[str, str]:
    """模块路径 -> 相对文件路径。"""
    out: dict[str, str] = {}
    for p in sorted(root.glob("**/*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        mod = rel[:-3].replace("/", ".")
        if mod.endswith(".__init__"):
            mod = mod[: -len(".__init__")]
        out[mod] = rel
    return out


def resolve_dependencies(
    chunks: list[Chunk],
    index: dict[str, str],
    top_k: int = 3,
    imports: dict[str, dict[str, str]] | None = None,
    modmap: dict[str, str] | None = None,
) -> None:
    """填 chunk.deps（1-hop）。解析优先级：同文件 > 同包 > 通过 import 跨文件 > 全局唯一名。

    跨文件边是本轮新增：没有它，依赖图会严重低估"改一个文件波及哪些结论"。
    """
    by_cid = {c.cid: c for c in chunks}
    by_file_name = {(c.path, c.name.split("#")[0]): c.cid for c in chunks}
    imports = imports or {}
    modmap = modmap or {}

    for c in chunks:
        deps: list[str] = []
        order = c.call_order or sorted(c.calls)
        for name in order:
            target = None
            # 1) 同文件
            same = by_file_name.get((c.path, name))
            if same and same != c.cid:
                target = same
            # 2) 跨文件 import
            if target is None and name in imports.get(c.path, {}):
                full = imports[c.path][name]
                for cand_mod in (full, full.rsplit(".", 1)[0]):
                    f = modmap.get(cand_mod)
                    if f:
                        hit = by_file_name.get((f, name))
                        if hit and hit != c.cid:
                            target = hit
                            break
            # 3) 全局唯一名
            if target is None:
                cands = [g for g in index.get(name, []) if g != c.cid and g in by_cid]
                if cands:
                    # 同名多候选：先同文件，再同类前缀，最后才退到全局首个
                    same_file = [g for g in cands if by_cid[g].path == c.path]
                    cls = c.name.split(".")[0] if "." in c.name else None
                    same_cls = [
                        g for g in cands
                        if cls and by_cid[g].name.startswith(cls + ".")
                    ]
                    target = (same_file or same_cls or cands)[0]
            if target and target not in deps:
                deps.append(target)
            if len(deps) >= top_k:
                break
        c.__dict__["deps"] = deps


def load_corpus(root: Path) -> tuple[list[Chunk], dict[str, str], dict[str, str]]:
    """统一入口：切块 + 符号索引 + 跨文件依赖解析。返回 (chunks, index, file_sha)。"""
    chunks = chunk_repo(root)
    index = build_symbol_index(chunks)
    resolve_dependencies(
        chunks, index, imports=collect_imports(root), modmap=module_file_map(root)
    )
    file_sha = {c.path: c.file_sha for c in chunks}
    return chunks, index, file_sha
