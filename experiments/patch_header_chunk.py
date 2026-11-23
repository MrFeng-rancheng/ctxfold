# -*- coding: utf-8 -*-
"""两处补齐：① 每个文件补一个「模块头」chunk（imports + 模块级常量）；② 查询含文件名时按文件加权。"""
import ast
import pathlib

CK = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\src\ctxfold\chunker.py")
s = CK.read_text(encoding="utf-8")

if "::<module>" not in s:
    anchor = '''    def visit(node, prefix: str = "") -> None:'''
    header = '''    # 模块头 chunk：imports + 模块级常量/赋值。
    # 真实 bug 常落在这里，而它们不属于任何函数，符号级切块会漏掉。
    head_lines: list[int] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)):
            head_lines.extend(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    if head_lines:
        head_lines = sorted(set(head_lines))
        text = "\\n".join(lines[i - 1] for i in head_lines if i - 1 < len(lines))
        if text.strip():
            out.append(Chunk(
                cid=f"{rel}::<module>",
                path=rel,
                name="<module>",
                kind="module",
                start=head_lines[0],
                end=head_lines[-1],
                text=text,
                tokens=token_count(text),
                file_sha=file_sha,
                calls=set(),
                call_order=[],
                call_qualified=[],
            ))

    def visit(node, prefix: str = "") -> None:'''
    assert anchor in s
    s = s.replace(anchor, header, 1)
    CK.write_text(s, encoding="utf-8")
    ast.parse(s)
    print("chunker: 模块头 chunk 已加")
else:
    print("chunker: 已有模块头")

AS = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\src\ctxfold\assembler.py")
t = AS.read_text(encoding="utf-8")
if "文件名命中" not in t:
    old = '''    qualified = [k for k in index if "." in k and k in query]'''
    new = '''    # 文件名命中：查询里出现 "xxx.py" 时，把该文件的 chunk 直接当首选命中，
    # 否则会被同名函数抢走（例如 tokenize.py 被 retrieve.py::tokenize 抢走）。
    for fn in re.findall(r"[A-Za-z0-9_./-]+\\.py", query):
        base = fn.rsplit("/", 1)[-1]
        for cid, ck in chunks_by_cid.items():
            if ck.path.rsplit("/", 1)[-1] == base and cid not in seen:
                seen.add(cid)
                hits.append((cid, True))

    qualified = [k for k in index if "." in k and k in query]'''
    assert old in t
    # _query_symbols 目前没有 chunks_by_cid 参数，这里改成按 index 反查不可行 → 用文件前缀过滤 cid
    new = '''    # 文件名命中：查询里出现 "xxx.py" 时，把该文件的 chunk 直接当首选命中，
    # 否则会被同名函数抢走（例如 tokenize.py 被 retrieve.py::tokenize 抢走）。
    for fn in re.findall(r"[A-Za-z0-9_./-]+\\.py", query):
        base = fn.rsplit("/", 1)[-1]
        for cid in index_cids:
            if cid.split("::")[0].rsplit("/", 1)[-1] == base and cid not in seen:
                seen.add(cid)
                hits.append((cid, True))

    qualified = [k for k in index if "." in k and k in query]'''
    t = t.replace(old, new, 1)
    # 从 index 反推所有 cid
    t = t.replace('''    hits: list[tuple[str, bool]] = []
    seen: set[str] = set()''',
                  '''    hits: list[tuple[str, bool]] = []
    seen: set[str] = set()
    index_cids = {cid for v in index.values() for cid in (v if isinstance(v, list) else [v])}''')
    AS.write_text(t, encoding="utf-8")
    ast.parse(t)
    print("assembler: 文件名加权已加")
else:
    print("assembler: 已有文件名加权")
