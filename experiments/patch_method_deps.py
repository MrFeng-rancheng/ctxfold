# -*- coding: utf-8 -*-
"""让对象方法调用进入依赖图：self.x() / Cls.x() / mod.x() 也能解析成 1 跳边。

做法（不动原有叶子名逻辑，只加一条"限定名优先"的通路）：
  1. 每个 chunk 额外收集 call_qualified = ["self.title", "HTTPMethod.__new__", ...]
  2. resolve_dependencies 先按限定名解析：
       self.f  -> 同文件的 "<本类>.f"
       Cls.f   -> 同文件 "<Cls>.f" > 全局索引 "Cls.f"
       mod.f   -> 走 import 表 -> 目标文件里的 f
     解析不到再回落到原来的叶子名三步。
  3. 仍然只在 top_k 内、仍然去重，避免边爆炸。
"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\src\ctxfold\chunker.py")
s = P.read_text(encoding="utf-8")
LOG = []


def rep(old, new, tag):
    global s
    if old not in s:
        print("[MISS]", tag)
        return
    s = s.replace(old, new, 1)
    LOG.append(tag)


# 1) Chunk 增加字段
rep("    call_order: list[str] = field(default_factory=list)  # 按出现顺序，避免字母序偏置",
    "    call_order: list[str] = field(default_factory=list)  # 按出现顺序，避免字母序偏置\n"
    "    call_qualified: list[str] = field(default_factory=list)  # 限定名调用：self.x / Cls.x / mod.x",
    "chunk-field")

# 2) 收集限定名
rep('''def chunk_file(path: Path, root: Path) -> list[Chunk]:''',
    '''def _collect_calls_qualified(node: ast.AST) -> list[str]:
    """收集带限定词的调用：self.f / Cls.f / mod.f（按出现顺序去重）。"""
    out: list[str] = []
    seen: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            q = sub.func.value
            qual = q.id if isinstance(q, ast.Name) else (q.attr if isinstance(q, ast.Attribute) else None)
            if not qual:
                continue
            full = f"{qual}.{sub.func.attr}"
            if full not in seen:
                seen.add(full)
                out.append(full)
    return out


def chunk_file(path: Path, root: Path) -> list[Chunk]:''', "collect-qualified")

# 3) 构造 Chunk 时填字段（call_order=... 那一行旁边）
rep("                call_order=_collect_calls(node),",
    "                call_order=_collect_calls(node),\n"
    "                call_qualified=_collect_calls_qualified(node),", "fill-field")

# 4) 解析：限定名优先
rep('''    for c in chunks:
        deps: list[str] = []
        order = c.call_order or sorted(c.calls)
        for name in order:''',
    '''    for c in chunks:
        deps: list[str] = []
        cls_of_c = c.name.split(".")[0] if "." in c.name else None
        qualified = list(getattr(c, "call_qualified", []) or [])

        # —— 第 0 步：限定名（self.x / Cls.x / mod.x）——
        for full in qualified:
            qual, leaf = full.rsplit(".", 1)
            target = None
            if qual == "self" and cls_of_c:
                target = by_file_name.get((c.path, f"{cls_of_c}.{leaf}"))
            elif qual in imports.get(c.path, {}):
                fullmod = imports[c.path][qual]
                for cand_mod in (fullmod, fullmod.rsplit(".", 1)[0]):
                    f = modmap.get(cand_mod)
                    if f:
                        hit = by_file_name.get((f, leaf))
                        if hit and hit != c.cid:
                            target = hit
                            break
            if target is None:
                hit = by_file_name.get((c.path, f"{qual}.{leaf}"))
                if hit and hit != c.cid:
                    target = hit
            if target is None:
                cands = [g for g in index.get(f"{qual}.{leaf}", []) if g != c.cid and g in by_cid]
                if len(cands) == 1:
                    target = cands[0]
            if target and target not in deps:
                deps.append(target)
            if len(deps) >= top_k:
                break

        order = c.call_order or sorted(c.calls)
        for name in order:
            if len(deps) >= top_k:
                break''', "resolve-qualified")

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("patched chunker:", ", ".join(LOG))
