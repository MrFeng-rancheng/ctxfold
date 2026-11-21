# -*- coding: utf-8 -*-
"""给检索加「标识符精确命中」修复：中英混排时 ASCII 标识符能被打中。

原实现对查询做 \\b 边界匹配，而标识符直接贴在汉字旁边（如「用ctxfold_doctor看看」）时
\\b 不成立，于是抽不出符号名 -> 真实会话里检索几乎全部落空。
修复用一组前后不要求 \\b 的正则，并保留开关：CTXFOLD_IDENT_FIX=1 时启用，默认不变，
以免影响论文里已经报告的数字。
"""
import ast
import pathlib

P = pathlib.Path(r"C:\Users\13956\Desktop\插件开发\ctxfold\src\ctxfold\assembler.py")
s = P.read_text(encoding="utf-8")

if "IDENT_FIX" not in s:
    # 1) 在 IDENT 定义后面插入修复版正则与开关
    anchor = None
    for line in s.splitlines():
        if line.startswith("IDENT"):
            anchor = line
            break
    assert anchor is not None, "MISS IDENT 定义"
    add = (anchor + "\n"
           "# 中英混排修复（开关式）：汉字紧贴标识符时 \\b 不成立，这里不要求词边界\n"
           "_IDENT_FIX = os.environ.get(\"CTXFOLD_IDENT_FIX\", \"\") not in (\"\", \"0\", \"false\", \"False\")\n"
           "IDENT_FIX = re.compile(r\"[A-Za-z_][A-Za-z0-9_]{2,}\")\n")
    s = s.replace(anchor + "\n", add, 1)

    # 2) 抽符号时按开关选正则
    s = s.replace("    for tok in IDENT.findall(query):",
                  "    _pat = IDENT_FIX if _IDENT_FIX else IDENT\n"
                  "    for tok in _pat.findall(query):", 1)

    # 3) 保证 os / re 已导入
    if "\nimport os" not in s:
        s = s.replace("\nimport re", "\nimport os\nimport re", 1) if "\nimport re" in s else s

P.write_text(s, encoding="utf-8")
ast.parse(s)
print("patched assembler:", "IDENT_FIX" in s, "| os imported:", "\nimport os" in s)
