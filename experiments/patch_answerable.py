# -*- coding: utf-8 -*-
"""给 m3_online 加 --answerable-only：只保留依赖题 gold 非空的题。"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\experiments\m3_online.py")
s = P.read_text(encoding="utf-8")

if "--answerable-only" in s:
    print("already patched")
    raise SystemExit(0)

old_arg = '    ap.add_argument("--mode", choices=["mock", "real"], default="mock")'
new_arg = (old_arg + "\n"
           '    ap.add_argument("--answerable-only", action="store_true",\n'
           '                    help="只保留依赖题 gold 非空的题（gold 为空的题按构造必错）")')
assert old_arg in s
s = s.replace(old_arg, new_arg, 1)

old_q = "    questions = make_questions(by_cid, chunks, args.tasks, args.seed)"
new_q = ('    questions = make_questions(by_cid, chunks, args.tasks * 2, args.seed)\n'
         '    if args.answerable_only:\n'
         '        questions = [q for q in questions if q["q_deps"]["gold"]][: args.tasks]')
assert old_q in s
s = s.replace(old_q, new_q, 1)

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("patched answerable-only")
