# -*- coding: utf-8 -*-
"""M14（v2）：传播精度——在临时副本上做改动，避免污染标准库。

结构失效集 I 由仓库依赖图给出（1 跳）；行为影响集 I* 由固定探针观测。
两类改动：
  (a) 只加一行注释（行为必然不变）——用来验证探针确实抓不到变化；
  (b) 改目标函数体（行为改变）——此时的「未变」才是真的过近似。
边界：单输入等价不等于语义等价，只报「探针观测下」的过近似率。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ctxfold.chunker import load_corpus  # noqa: E402

STDLIB = Path(r"C:\Users\13956\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\Lib")
SRC = STDLIB / "http" / "cookiejar.py"

PROBES = [
    ("strip_quotes", "m.strip_quotes('\"abc\"')"),
    ("split_header_words", "m.split_header_words(['a=b; Path=/; HttpOnly', 'x=y'])"),
    ("parse_ns_headers", "m.parse_ns_headers(['a=b; Path=/', 'c=d; Domain=.e.com'])"),
    ("is_HDN", "m.is_HDN('example.com')"),
    ("domain_match", "m.domain_match('a.example.com', '.example.com')"),
    ("join_header_words", "m.join_header_words([('a', 'b'), ('c', 'd')])"),
    ("parse_ns_headers_v2", "m.parse_ns_headers(['q=1; Version=1'])"),
    ("split_header_words_v2", "m.split_header_words(['k=v; flag'])"),
]


def install_copy(tmp: Path) -> Path:
    dst = tmp / "cjm_probe.py"
    shutil.copyfile(SRC, dst)
    return dst


def probe_all(tmp: Path) -> dict:
    sys.path.insert(0, str(tmp))
    for k in [m for m in list(sys.modules) if m == "cjm_probe"]:
        sys.modules.pop(k, None)
    import cjm_probe as m  # noqa: F811
    try:
        out = {}
        for name, expr in PROBES:
            try:
                out[name] = repr(eval(expr))
            except Exception as e:
                out[name] = f"ERR {type(e).__name__}"
        return out
    finally:
        sys.path.remove(str(tmp))
        sys.modules.pop("cjm_probe", None)


def add_comment(src: str) -> str:
    return src.replace("def split_header_words", "# m14 touch\ndef split_header_words", 1)


def change_body(src: str) -> str:
    lines = src.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("def split_header_words("):
            out.append(lines[i])
            i += 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                i += 1
            out.append("    return []\n\n")
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def main() -> int:
    chunks, _index, _sha = load_corpus(STDLIB / "http")
    by = {c.cid: c for c in chunks}
    rev: dict[str, set[str]] = {}
    for cid, ck in by.items():
        for dep in getattr(ck, "deps", []) or []:
            rev.setdefault(dep, set()).add(cid)

    tgt = "cookiejar.py::split_header_words"
    I = {tgt} | rev.get(tgt, set())
    print("结构失效集 I =", sorted(I))

    tmp = Path(tempfile.mkdtemp(prefix="m14-"))
    dst = install_copy(tmp)
    base_src = SRC.read_text(encoding="utf-8")
    base = probe_all(tmp)
    print("基准:", base)

    rows = []
    for label, fn in (("只加一行注释", add_comment), ("改函数体返回空表", change_body)):
        dst.write_text(fn(base_src), encoding="utf-8")
        outs = probe_all(tmp)
        changed = [k for k in base if base[k] != outs.get(k)]
        rows.append({"mutation": label, "I_size": len(I), "probes": len(base),
                     "I_star_probe": len(changed), "changed_probes": changed,
                     "outputs": outs})
        print(f"{label}: 变了 {len(changed)}/{len(base)} -> {changed}")

    dst.write_text(base_src, encoding="utf-8")
    path = ROOT / "experiments" / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-m14")
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.json").write_text(json.dumps(
        {"manifest": {"corpus": str(STDLIB / "http"), "target": tgt, "I": sorted(I)},
         "baseline": base, "rows": rows}, ensure_ascii=False, indent=2), "utf-8")

    lines = ["# m14 传播精度（自动生成，勿手改）", "",
             f"目标符号 `{tgt}`，1 跳结构失效集 |I| = {len(I)}；探针 {len(base)} 个（单输入）。", "",
             "| 改动 | 结构失效集 | 探针数 | 探针观测到变化 |", "| --- | --- | --- | --- |"]
    for r in rows:
        lines.append("| %s | %d | %d | %d |" % (r["mutation"], r["I_size"], r["probes"], r["I_star_probe"]))
    lines += ["", "基准值：", ""] + [f"- `{k}` -> {v}" for k, v in base.items()]
    (ROOT / "experiments" / "RESULTS-m14.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("run dir:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
