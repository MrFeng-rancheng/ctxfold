"""bundle_paper：把论文与实验材料打包到指定目录（默认桌面/插件开发）。

产出：
  <out>/ctxfold-paper-<date>.zip        论文 + 附录 + 协议 + 结果表 + 笔记 + INDEX
  <out>/ctxfold-paper-<date>/全文.md    论文与附录合并成的单文件（便于通读/转 Word）

用法：
  python scripts/bundle_paper.py --out "C:/Users/13956/Desktop/插件开发"
"""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PARTS = [
    ("01-论文正文.md", "docs/paper-draft.md"),
    ("02-实验附录.md", "docs/appendix-experiments.md"),
    ("03-预注册协议.md", "docs/protocol.md"),
    ("04-结果表.md", "experiments/RESULTS.md"),
    ("05-多种子方差.md", "experiments/SEEDS.md"),
    ("06-实验笔记.md", "notes/2026-11-12.md"),
    ("07-设计文档.md", "docs/design.md"),
    ("08-路线图与封锁项.md", "docs/roadmap.md"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:/Users/13956/Desktop/插件开发")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"ctxfold-paper-{date.today().isoformat()}"

    files = []
    for name, rel in PARTS:
        p = ROOT / rel
        if p.exists():
            files.append((name, p))
        else:
            print(f"[warn] 缺失：{rel}")
    files.append(("09-封锁项.md", ROOT / "docs/BLOCKERS.md"))

    index = [
        f"# ctxfold 论文材料包（{date.today().isoformat()}）",
        "",
        "本包内容与仓库内文件一一对应，数字可复现（见 03-预注册协议.md 与 04-结果表.md）。",
        "",
        "| 文件 | 说明 |",
        "|---|---|",
        "| 01-论文正文.md | 命题 + RQ1–RQ7 + 12 条效度威胁 |",
        "| 02-实验附录.md | 每个数字的来源、设置、复现命令与缺陷（A.1–A.15） |",
        "| 03-预注册协议.md | 指标定义、判据、修订记录（含在线实验预注册 §9） |",
        "| 04-结果表.md | 离线实验自动生成结果（勿手改） |",
        "| 05-多种子方差.md | 5 seed 均值 ± 标准差 |",
        "| 06-实验笔记.md | 逐轮工作记录（含失败与自我批评） |",
        "| 07-设计文档.md | 数据结构、guard、世界指纹、失效传播 |",
        "| 08-路线图与封锁项.md | 里程碑与剩余缺口 |",
        "| 09-封锁项.md | 还差什么、怎么解锁 |",
        "",
        "## 核心数字（真实测量）",
        "",
        "- 离线：累计输入 token 降至全量基线的 **7.9%**（305,768 → 24,282，5 seed 均值），",
        "  为最强基线 BM25 检索的 **56%**；严格可见证据率 0.633 vs 0.703。",
        "- 在线（deepseek-chat，3 次运行）：定位题 **1.000**、依赖 gold 召回 0.845–1.000、",
        "  语义题 0.700–0.833、**H 免算率 0.322–0.333**、**recall 触发率 0.567–0.633**。",
        "- 在线 E（模型自写可执行断言，n=12）：**0.417**。",
        "",
        "## 一句话",
        "",
        "把上下文从「重演历史」改为「维护带守卫的结论状态」：已知内容不重复付费，",
        "需要细节时按需取回。代价是「当场可见」变成「按需取回」，收益与模型 recall 倾向强相关。",
    ]
    (out / f"{tag}-INDEX.md").write_text("\n".join(index), encoding="utf-8")

    # 单文件全文
    merged = []
    for name, p in files[:2]:
        merged.append(p.read_text(encoding="utf-8"))
        merged.append("\n\n---\n\n")
    (out / f"{tag}-全文.md").write_text("".join(merged), encoding="utf-8")

    zpath = out / f"{tag}.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{tag}/00-INDEX.md", "\n".join(index))
        for name, p in files:
            z.write(p, arcname=f"{tag}/{name}")
        z.write(out / f"{tag}-全文.md", arcname=f"{tag}/10-全文合并.md")

    data = zpath.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    (out / f"{tag}.sha256").write_text(f"{sha}  {zpath.name}\n", encoding="utf-8")

    print(f"输出目录: {out}")
    print(f"  压缩包: {zpath.name}  ({len(data)/1024:.1f} KiB, {len(files)+2} 个文件)")
    print(f"  全文:   {tag}-全文.md")
    print(f"  索引:   {tag}-INDEX.md")
    print(f"  sha256: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
