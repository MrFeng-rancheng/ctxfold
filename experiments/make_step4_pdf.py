# -*- coding: utf-8 -*-
"""生成「第 4 步 多步编码任务」单页报告：只用任务来源 + 现象 + 数字，不加设计与边界章节。"""
from __future__ import annotations

import ast
import json
import pathlib
import statistics
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments"
RUNS = [EXP / "runs" / f"20261123-{t}-m22" for t in ("013703", "013923", "014138")]
OUT_DOCX = ROOT.parent / "paper_build" / "第4步-多步编码任务-现象与数字.docx"
METHODS = ["full", "grepriag", "ours"]
LABEL = {"full": "全量历史", "grepriag": "BM25 检索", "ours": "ctxfold 运行时"}


def tasks() -> list[dict]:
    src = (EXP / "m22_coding.py").read_text("utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "TASKS":
            return ast.literal_eval(node.value)
    raise SystemExit("TASKS 未找到")


def rows() -> list[dict]:
    out = []
    for d in RUNS:
        out += json.loads((d / "summary.json").read_text("utf-8"))["rows"]
    return out


def cn(run, size=None, bold=False):
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    if size:
        run.font.size = Pt(size)
    run.bold = bold


def para(doc, text, size=10.5, bold=False, align=None, space=4):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space)
    p.paragraph_format.line_spacing = 1.15
    if align is not None:
        p.alignment = align
    cn(p.add_run(text), size, bold)
    return p


def table(doc, cap, header, body, widths, font=8.5):
    para(doc, cap, 9, True, WD_ALIGN_PARAGRAPH.CENTER, 3)
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cn(p.add_run(h), font, True)
    for r in body:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i else WD_ALIGN_PARAGRAPH.LEFT
            cn(p.add_run(str(v)), font)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
    return t


def main() -> int:
    T = tasks()
    R = rows()
    names = [t["name"] for t in T]
    active = [n for n in names if any(r["task"] == n for r in R)]
    skipped = [n for n in names if n not in active]

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.8)
    sec.top_margin = sec.bottom_margin = Cm(1.6)
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    para(doc, "第 4 步　多步编码任务：任务来源、现象与数字", 15, True, WD_ALIGN_PARAGRAPH.CENTER, 2)
    para(doc, "数据来源 runs/20261123-013703-m22、runs/20261123-013923-m22、runs/20261123-014138-m22；"
              "模型 deepseek-ai/DeepSeek-V3.2，温度 0；每个（任务，方法）重复 3 次，共 99 个 run。",
         8.5, False, WD_ALIGN_PARAGRAPH.CENTER, 8)

    # 一、用了哪一批任务
    para(doc, "一、用了哪一批任务", 12, True, space=4)
    para(doc, f"任务全部定义在 experiments/m22_coding.py 的 TASKS 中，共 {len(names)} 条；"
              f"执行前逐条做可观测性预检（注入 bug 后必须先让测试失败），其中 {len(skipped)} 条被剔除，"
              f"实际参与 {len(active)} 条：" + ("、".join(skipped) if skipped else "无") + "。"
              "缺陷都是脚本向被测仓库 ctxfold 的某个源文件注入 1—2 行，测试为临时写在 tests/test_task.py 的 pytest 用例，"
              "通过与否只看 pytest 退出码。", 9.5, space=6)
    table(doc, "表 1　参与实验的 11 个任务",
          ["编号", "被测文件", "任务"],
          [[t["name"].split()[0], t["file"], t["name"].split(" ", 1)[1]] for t in T if t["name"] in active],
          [1.4, 3.0, 12.6])

    # 二、现象
    para(doc, "二、现象", 12, True, space=4)
    body = []
    for m in METHODS:
        rs = [r for r in R if r["method"] == m]
        n, p = len(rs), sum(1 for r in rs if r["passed"])
        body.append([LABEL[m], n, p, f"{p / n:.1%}",
                     f"{statistics.mean([r['tokens'] for r in rs]):,.0f}",
                     f"{statistics.median([r['tokens'] for r in rs]):,.0f}",
                     f"{statistics.mean([r['steps'] for r in rs]):.2f}",
                     f"{statistics.mean([r['seconds'] for r in rs]):.1f}",
                     f"{statistics.mean([len(r['invalidations']) for r in rs]):.2f}"])
    table(doc, "表 2　三种上下文供给在 11 个任务上的汇总",
          ["供给方式", "n", "通过", "通过率", "token 均值", "token 中位", "步数均值", "耗时均值", "失效/次"],
          body, [3.4, 1.0, 1.2, 1.6, 2.1, 2.1, 1.7, 1.7, 1.5])

    body = []
    for t in T:
        n = t["name"]
        if n not in active:
            continue
        row = [n.split()[0] + " " + n.split(" ", 1)[1]]
        for m in METHODS:
            rs = [r for r in R if r["task"] == n and r["method"] == m]
            ok = sum(1 for r in rs if r["passed"])
            row.append(f"{ok}/{len(rs)}")
            row.append(f"{statistics.median([r['tokens'] for r in rs]):,.0f}")
        body.append(row)
    table(doc, "表 3　逐任务通过次数与 token 中位",
          ["任务", "全量·通过", "全量·token", "BM25·通过", "BM25·token", "ctxfold·通过", "ctxfold·token"],
          body, [5.0, 1.95, 2.0, 1.95, 2.0, 1.95, 2.0], font=7.5)

    stable = [t["name"] for t in T if any(r["task"] == t["name"] and r["method"] == "full" and r["passed"] for r in R)]
    body = []
    for m in METHODS:
        rs = [r for r in R if r["method"] == m and r["task"] in stable]
        p = sum(1 for r in rs if r["passed"])
        body.append([LABEL[m], len(rs), f"{p / len(rs):.1%}",
                     f"{statistics.mean([r['tokens'] for r in rs]):,.0f}"])
    table(doc, f"表 4　可解子集（全量历史至少通过一次的 {len(stable)} 个任务）",
          ["供给方式", "n", "通过率", "token 均值"], body, [4.4, 1.4, 2.2, 2.6])

    para(doc, "五条现象：", 9.5, True, space=3)
    for line in [
        "（1）ctxfold 的通过率比全量历史高 12.1 个百分点（69.7% 对 57.6%），但 token 少 48%（5 138 对 9 869），"
        "在可解子集上两者是 95.2% 对 90.5%、2 710 对 4 956，差距主要落在成本上。",
        "（2）T9（快照键唯一性）是全量历史唯一输给 ctxfold 的任务：1/3 对 3/3；它要改的正是状态模块本身，"
        "整文件塞进提示后模型在长文里挑错了替换窗口。",
        "（3）T11（遍历应跳过缓存目录）方向相反：BM25 检索 3/3、全量历史 0/3、ctxfold 3/3，"
        "给得少但给对位置比给得全更有用。",
        "（4）BM25 检索在 11 个任务上只过 3 次，全部来自 T11，步数均值 2.82（另两者为 1.91 与 1.61）："
        "它按失败文本召回，拿不到「改哪一行」，补丁对不上就反复重试。",
        "（5）T3 改格式化字符串、T7 未加载块标题、T8 结论块标题三条，三种供给都是 0/3，全量历史也一样，"
        "原因是答案要求猜出精确字符串，属任务本身不可解，已从可解子集剔除。",
    ]:
        para(doc, line, 9.5, space=2)

    para(doc, "三、数字", 12, True, space=4)
    tok = {m: [r["tokens"] for r in R if r["method"] == m] for m in METHODS}
    stp = {m: [r["steps"] for r in R if r["method"] == m] for m in METHODS}
    para(doc, "总量：99 个 run 的输入 token 合计 "
              + "、".join(f"{LABEL[m]} {sum(tok[m]):,}" for m in METHODS)
              + "；平均每步 "
              + "、".join(f"{LABEL[m]} {statistics.mean(tok[m]) / statistics.mean(stp[m]):,.0f}"
                          for m in METHODS) + " token。", 9.5, space=3)
    para(doc, "改动后失效：ctxfold 每次运行平均触发 1.24 次状态失效（合计 "
              f"{sum(len(r['invalidations']) for r in R if r['method'] == 'ours')} 次分步记录），"
              "另外两种供给没有状态层，该栏为空。", 9.5, space=3)
    para(doc, "极值：单次 run 最大输入 token " + f"{max(r['tokens'] for r in R):,}（"
              + max(R, key=lambda r: r["tokens"])["task"] + " / " + LABEL[max(R, key=lambda r: r["tokens"])["method"]]
              + "），最小 " + f"{min(r['tokens'] for r in R):,}（"
              + min(R, key=lambda r: r["tokens"])["task"] + " / " + LABEL[min(R, key=lambda r: r["tokens"])["method"]] + "）。",
         9.5, space=3)

    doc.save(str(OUT_DOCX))
    print("saved:", OUT_DOCX, OUT_DOCX.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
