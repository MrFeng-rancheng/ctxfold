# -*- coding: utf-8 -*-
"""M21 的第三版：改动改成"整段替换函数体"，避免旧行为残留在文本里迷惑模型。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m21_mutation.py")
s = P.read_text(encoding="utf-8")

# 1) 加一个"替换整个函数体"的工具
helper = '''def replace_body(src: str, header: str, new_body: str) -> str:
    """把 header（如 '    def decode('）开始的整个函数体替换成 new_body。"""
    i = src.index(header)
    j = i + len(header)
    while j < len(src) and src[j] != "\\n":
        j += 1
    j += 1
    k = j
    while k < len(src):
        line_end = src.find("\\n", k)
        line_end = len(src) if line_end < 0 else line_end
        line = src[k:line_end]
        if line.strip() and not line.startswith((" ", "\\t")):
            break
        if line.strip().startswith("def ") and line.startswith("    "):
            break
        k = line_end + 1
    return src[:j] + new_body + src[k:]


'''
s = s.replace("def build_repo(", helper + "def build_repo(", 1)

# 2) 三个场景：整段替换 + 无歧义探针
start = s.index("S1_MUT = ")
end = s.index("def probe(")
new_scen = '''S1_MUT = lambda s: replace_body(s, "    def decode(self, s, _w=WHITESPACE.match):",
                                "        raise ValueError('m21')  # mutated\\n")
S2_MUT = lambda s: replace_body(s, "    def encode(self, o):",
                                "        return b'{}'  # mutated\\n")
S3_MUT = lambda s: replace_body(s, "    def raw_decode(self, s, idx=0):",
                                "        return (42, len(s))  # mutated\\n")

ASK_DECODE_EXC = "JSONDecoder 的 decode 方法遇到非法转义时会抛出什么异常类型？只回答类名。"
ASK_ENCODE_TYPE = "JSONEncoder 的 encode 方法返回什么类型？只回答类型名。"
ASK_DECODE_TYPE = "JSONDecoder 的 decode 方法正常解码后返回什么类型？只回答类型名。"

SCEN = [
    {"name": "S1 改自身（decode 抛异常）", "file": "decoder.py", "ask": ASK_DECODE_EXC,
     "probe": f"type((lambda: m.JSONDecoder().decode({BAD!r}))()).__name__",
     "mutate": S1_MUT, "extra_ask": "raw_decode 这个名字是否存在？只回答名字本身。"},
    {"name": "S2 改返回（encode 类型）", "file": "encoder.py", "ask": ASK_ENCODE_TYPE,
     "probe": "type(m.JSONEncoder().encode({'a': 1})).__name__",
     "mutate": S2_MUT, "extra_ask": "encode_basestring 这个名字是否存在？只回答名字本身。"},
    {"name": "S3 改下游（raw_decode 返回值）", "file": "decoder.py", "ask": ASK_DECODE_TYPE,
     "probe": "type(m.JSONDecoder().decode('{\\"a\\": 1}')).__name__",
     "mutate": S3_MUT, "extra_ask": "raw_decode 这个名字是否存在？只回答名字本身。"},
]


'''
s = s[:start] + new_scen + s[end:]
P.write_text(s, encoding="utf-8")
ast.parse(s)
print("m21 v3 written")
