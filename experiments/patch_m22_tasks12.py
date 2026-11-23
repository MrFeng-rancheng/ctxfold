# -*- coding: utf-8 -*-
"""把 m22 的任务库扩到 12 个，并加 --precheck 模式（只验证 bug 是否可观测）。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m22_coding.py")
s = P.read_text(encoding="utf-8")

start = s.index("TASKS = [")
end = s.index("def build_repo(")
NEW = '''TASKS = [
    {"name": "T1 改模块常量", "file": "tokenize.py",
     "bug": ("_CHARS_PER_TOKEN = 3.5", "_CHARS_PER_TOKEN = 2.0"),
     "test": "from ctxfold.tokenize import token_count\\n\\n\\ndef test_empty():\\n"
             "    assert token_count('') == 0\\n\\n\\ndef test_nonempty():\\n"
             "    assert token_count('abcdefg') == 2\\n"},
    {"name": "T2 改函数返回值", "file": "tokenize.py",
     "bug": ("def char_count(text: str) -> int:\\n    return len(text)",
             "def char_count(text: str) -> int:\\n    return len(text) + 1"),
     "test": "from ctxfold.tokenize import char_count\\n\\n\\ndef test_len():\\n"
             "    assert char_count('abc') == 3\\n"},
    {"name": "T3 改格式化字符串", "file": "assembler.py",
     "bug": ('        lines.append(f"- #{cid} ({m.name})")',
             '        lines.append(f"- {cid} ({m.name})")'),
     "test": "from ctxfold.assembler import _placeholders\\n\\n\\nclass M:\\n    name = 'f'\\n\\n\\n"
             "def test_hash():\\n    out = _placeholders({'x::f': M()}, ['x::f'])\\n"
             "    assert '#x::f' in out\\n"},
    {"name": "T5 改 AST 解析分支", "file": "chunker.py",
     "bug": ("            elif isinstance(fn, ast.Attribute):\\n                n = fn.attr",
             "            elif isinstance(fn, ast.Attribute):\\n                n = None"),
     "test": "import ast\\nfrom ctxfold.chunker import _collect_calls\\n\\n\\ndef test_attr():\\n"
             "    node = ast.parse('x.append(1)')\\n    assert _collect_calls(node) == ['append']\\n"},
    {"name": "T6 改指纹实现", "file": "world.py",
     "bug": ('    return h.hexdigest()[:16]', "    return 'fixed0000000000'"),
     "test": "import pathlib, tempfile\\nfrom ctxfold.world import cheap_fingerprint\\n\\n\\n"
             "def test_change():\\n    d = pathlib.Path(tempfile.mkdtemp())\\n"
             "    f = d / 'a.py'\\n    f.write_text('x=1\\\\n', encoding='utf-8')\\n"
             "    a = cheap_fingerprint(d)\\n    f.write_text('x=2\\\\n' * 5, encoding='utf-8')\\n"
             "    assert cheap_fingerprint(d) != a\\n"},
    {"name": "T7 未加载块标题", "file": "assembler.py",
     "bug": ('        lines = ["[未加载，按需 recall 取原文]"]', "        lines = []"),
     "test": "from ctxfold.assembler import _recallable\\n\\n\\nclass C:\\n    name = 'f'\\n\\n\\n"
             "def test_head():\\n    out = _recallable({'x::f': C()}, ['x::f'])\\n"
             "    assert '未加载' in out\\n"},
    {"name": "T8 结论块标题", "file": "assembler.py",
     "bug": ('        lines = ["[已验证结论：可直接采用，无需重读代码]"]', "        lines = []"),
     "test": "from ctxfold.assembler import _claims\\n\\n\\nclass M:\\n    claim = 'c'\\n\\n\\n"
             "def test_head():\\n    out = _claims({'x::f': M()}, ['x::f'])\\n"
             "    assert '已验证结论' in out\\n"},
    {"name": "T9 快照键唯一性", "file": "state.py",
     "bug": ('            return f"{safe}.{hashlib.sha1(cid.encode(\\'utf-8\\')).hexdigest()[:8]}"',
             '            return f"{safe}"'),
     "test": "import pathlib, tempfile\\nfrom ctxfold.state import StateRuntime\\n\\n\\n"
             "def test_key():\\n    d = pathlib.Path(tempfile.mkdtemp())\\n"
             "    (d / 'a.py').write_text('def f():\\\\n    return 1\\\\n', encoding='utf-8')\\n"
             "    st = StateRuntime(d, d / 'st')\\n"
             "    assert st._snap_key('a/b::f') != st._snap_key('a_b::f')\\n"},
    {"name": "T10 内容指纹应随内容变", "file": "world.py",
     "bug": ("            h.update(hashlib.sha256(p.read_bytes()).digest())",
             '            h.update(b"")'),
     "test": "import pathlib, tempfile\\nfrom ctxfold.world import content_fingerprint\\n\\n\\n"
             "def test_change():\\n    d = pathlib.Path(tempfile.mkdtemp())\\n"
             "    f = d / 'a.py'\\n    f.write_text('x=1\\\\n', encoding='utf-8')\\n"
             "    a = content_fingerprint(d)\\n    f.write_text('y=2\\\\n', encoding='utf-8')\\n"
             "    assert content_fingerprint(d) != a\\n"},
    {"name": "T11 遍历应跳过缓存目录", "file": "world.py",
     "bug": ('        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]',
             "        dirnames[:] = dirnames"),
     "test": "import pathlib, tempfile\\nfrom ctxfold.world import _iter_py\\n\\n\\n"
             "def test_skip():\\n    d = pathlib.Path(tempfile.mkdtemp())\\n"
             "    (d / 'a.py').write_text('x=1\\\\n', encoding='utf-8')\\n"
             "    c = d / '__pycache__'\\n    c.mkdir()\\n"
             "    (c / 'b.py').write_text('y=1\\\\n', encoding='utf-8')\\n"
             "    names = [p.name for p in _iter_py(d)]\\n    assert 'b.py' not in names\\n"},
    {"name": "T12 top_k 应遵守 k", "file": "retrieve.py",
     "bug": ("            if len(out) >= k:", "            if len(out) >= k + 1:"),
     "test": "import pathlib, tempfile\\nfrom ctxfold.chunker import load_corpus\\n"
             "from ctxfold.retrieve import BM25\\n\\n\\ndef test_k():\\n"
             "    d = pathlib.Path(tempfile.mkdtemp())\\n"
             "    for i in range(4):\\n        (d / f'm{i}.py').write_text('def f%d():\\\\n    return %d\\\\n' % (i, i), encoding='utf-8')\\n"
             "    chunks, index, sha = load_corpus(d)\\n    bm = BM25(chunks)\\n"
             "    assert len(bm.top_k('f1', k=2)) <= 2\\n"},
    {"name": "T13 调用顺序应保持源码序", "file": "chunker.py",
     "bug": ("                names.append(n)\\n    return names",
             "                names.append(n)\\n    return sorted(names)"),
     "test": "import ast\\nfrom ctxfold.chunker import _collect_calls\\n\\n\\ndef test_order():\\n"
             "    node = ast.parse('b()\\\\na()')\\n    assert _collect_calls(node) == ['b', 'a']\\n"},
]


'''
s = s[:start] + NEW + s[end:]

# precheck 模式
if "CTX_M22_PRECHECK" not in s:
    s = s.replace('''        bad, _ = run_tests(probe_repo)''',
                  '''        bad, _ = run_tests(probe_repo)
        if os.environ.get("CTX_M22_PRECHECK"):
            print(f"{task['name'][:24]:24s} {'可观测' if bad else '不可观测(跳过)'}", flush=True)
            continue''')

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("m22: 12 个任务 + precheck 已就绪")
