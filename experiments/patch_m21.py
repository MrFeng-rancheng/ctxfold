# -*- coding: utf-8 -*-
"""修 M21：探针改成"整文件 exec、保留真实 import"，并让三个场景的改前/改后真值确实不同。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m21_mutation.py")
s = P.read_text(encoding="utf-8")

# 1) probe：不再动 import 行
old_probe = '''    holder = {}
    src = module_file.read_text(encoding="utf-8").replace("from json import scanner", "scanner = None")
    mod = types.ModuleType("probe_mod")
    mod.__dict__["__file__"] = str(module_file)
    holder["m"] = mod
    try:
        exec(compile(src, str(module_file), "exec"), mod.__dict__)
        return repr(eval(expr, mod.__dict__))
    except Exception as e:
        return f"EXC {type(e).__name__}"'''
new_probe = '''    src = module_file.read_text(encoding="utf-8")
    mod = types.ModuleType("probe_mod")
    mod.__dict__["__file__"] = str(module_file)
    mod.__dict__["__name__"] = "probe_mod"
    try:
        exec(compile(src, str(module_file), "exec"), mod.__dict__)
        return repr(eval(expr, mod.__dict__))
    except Exception as e:
        return f"EXC {type(e).__name__}"'''
assert old_probe in s
s = s.replace(old_probe, new_probe, 1)

# 2) 三个场景：真值确实会变
start = s.index("SCEN = [")
end = s.index("]\n\n\ndef build_repo")
new_scen = '''SCEN = [
    {"name": "S1 改抛出分支", "file": "decoder.py",
     "ask": "解码字符串 \\"\\\\\\\\q\\"（反斜杠后跟 q）会抛出什么异常类型？只回答类名。",
     "probe": "type((lambda: m.JSONDecoder().decode('\\"\\\\\\\\q\\"'))()).__name__",
     "mutate": lambda s: s.replace("raise JSONDecodeError(msg, s, end)", "raise ValueError(msg)  # m21", 1),
     "extra": "py_make_scanner",
     "extra_ask": "py_make_scanner 这个名字是否存在？只回答名字本身。"},
    {"name": "S2 改返回类型", "file": "encoder.py",
     "ask": "JSONEncoder().encode({'a': 1}) 返回什么类型？只回答类型名。",
     "probe": "type(m.JSONEncoder().encode({'a': 1})).__name__",
     "mutate": lambda s: s.replace("def encode(self, o):",
                                   "def encode(self, o):\\n        return b'{}'  # m21", 1),
     "extra": "encode_basestring",
     "extra_ask": "encode_basestring 这个名字是否存在？只回答名字本身。"},
    {"name": "S3 改下游（1 跳）", "file": "decoder.py",
     "ask": "解码字符串 \\"\\\\\\\\q\\" 会抛出什么异常类型？只回答类名。",
     "probe": "type((lambda: m.JSONDecoder().decode('\\"\\\\\\\\q\\"'))()).__name__",
     "mutate": lambda s: s.replace("def py_scanstring(",
                                   "def py_scanstring(*a, **k):\\n    raise KeyError('m21')\\n\\n\\ndef _m21_orig(", 1),
     "extra": "JSONDecoder",
     "extra_ask": "JSONDecoder 这个名字是否存在？只回答名字本身。"},
'''
s = s[:start] + new_scen + s[end:]

# 3) 记录 downstream
s = s.replace('"invalidated": invalidated, "kept": kept, "turns": turns,',
              '"invalidated": invalidated, "downstream": info_downstream, "kept": kept, "turns": turns,')
s = s.replace("    invalidated, kept = [], []", "    invalidated, kept, info_downstream = [], [], []")
s = s.replace('invalidated, kept = info["invalidated"], info["kept"]',
              'invalidated, kept = info["invalidated"], info["kept"]\n                info_downstream = info["downstream"]')
s = s.replace('f"改后答对={r[\'correct_after\']} 失效={len(r[\'invalidated\'])} 保留={len(r[\'kept\'])}"',
              'f"改后答对={r[\'correct_after\']} 自身失效={len(r[\'invalidated\'])} 波及={len(r[\'downstream\'])} 保留={len(r[\'kept\'])}"')

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("patched m21")
