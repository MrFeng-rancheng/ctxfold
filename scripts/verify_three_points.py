# -*- coding: utf-8 -*-
"""三条要求的端到端验证（CLI / stdio 服务 / DSH 插件工具 三条通路都走）。

  ① 删掉 skill/ 目录后，核心状态机与装配仍独立运行
  ② 每个 raw 块带 `### #<cid> | <file>:<start>-<end>`；每个非 raw 项（card/claim/placeholder）
     都能按 ID 取回原文；文件改动之后仍能取回"当初那段"（快照，unchanged=false）
  ③ 改一个符号后：对应结论失效、下游被波及、未改动部分继续复用

用法：python scripts/verify_three_points.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PLUGIN = ROOT.parent / "dsh-ctxfold" / "index.js"
PY = sys.executable
HEADER_RE = re.compile(r"^### #(?P<cid>[^\s|]+) \| (?P<path>[^:]+):(?P<start>\d+)-(?P<end>\d+)$")

FILES = {
    "base.py": "def add(a, b):\n    return a + b\n",
    "mid.py": "from base import add\n\n\ndef total(xs):\n    s = 0\n    for x in xs:\n        s = add(s, x)\n    return s\n",
    "top.py": "from mid import total\n\n\ndef average(xs):\n    if not xs:\n        return 0\n    return total(xs) / len(xs)\n",
    "other.py": "def unrelated(x):\n    return x * 2\n",
}
RESULTS: dict[str, bool] = {}


def env_for() -> dict:
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC) + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e["PYTHONIOENCODING"] = "utf-8"
    e["CTXFOLD_PYTHON"] = PY
    return e


def cli(repo: Path, state: Path, *argv: str, budget: int | None = None) -> subprocess.CompletedProcess:
    head = [PY, "-m", "ctxfold.cli", "--corpus", str(repo), "--state", str(state)]
    if budget:
        head += ["--budget", str(budget)]
    return subprocess.run(head + list(argv), capture_output=True, text=True,
                          encoding="utf-8", env=env_for())


def service(repo: Path, state: Path, reqs: list[dict], budget: int | None = None) -> list[dict]:
    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in reqs) + "\n"
    head = [PY, "-m", "ctxfold.cli", "--corpus", str(repo), "--state", str(state)]
    if budget:
        head += ["--budget", str(budget)]
    p = subprocess.run(head + ["serve"], input=lines, capture_output=True, text=True,
                       encoding="utf-8", env=env_for())
    return [json.loads(x) for x in p.stdout.splitlines() if x.strip()]


NODE_HARNESS = r"""
const plugin = require(process.env.CTX_PLUGIN)
const tools = {}
plugin.apply({ tools: { register: (t) => { tools[t.name] = t } } }, { enabled: true })
;(async () => {
  const out = []
  for (const c of JSON.parse(process.env.CTX_CALLS)) {
    const t = tools[c.tool]
    if (!t) { out.push({ error: 'no such tool: ' + c.tool }); continue }
    try { out.push({ text: (await t.execute(c.args)).text }) }
    catch (e) { out.push({ error: String(e) }) }
  }
  process.stdout.write(JSON.stringify({ tools: Object.keys(tools), out }))
})()
"""


def plugin_calls(repo: Path, calls: list[dict]) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(NODE_HARNESS)
        harness = f.name
    env = env_for()
    env["CTX_PLUGIN"] = str(PLUGIN)
    env["CTX_CALLS"] = json.dumps(calls, ensure_ascii=False)
    try:
        p = subprocess.run(["node", harness], capture_output=True, text=True, encoding="utf-8", env=env)
        if p.returncode != 0:
            return {"error": (p.stderr or p.stdout)[-400:]}
        return json.loads(p.stdout)
    finally:
        os.unlink(harness)


def assemble(repo: Path, state: Path, query: str, budget: int | None = None) -> dict:
    r = service(repo, state, [{"id": 1, "op": "assemble", "args": {"query": query}}, {"id": 2, "op": "close"}],
                budget=budget)
    assert r and r[0].get("ok"), r
    return r[0]["result"]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ctxfold-3pts-"))
    repo = tmp / "repo"
    repo.mkdir()
    for name, body in FILES.items():
        (repo / name).write_text(body, encoding="utf-8")

    # ---------------- ① ----------------
    print("=" * 72)
    print("① 删掉 skill/ 后，三条通路是否都还能跑")
    print("=" * 72)
    skill, backup = ROOT / "skill", tmp / "skill-backup"
    moved = False
    if skill.exists():
        shutil.move(str(skill), str(backup)); moved = True
        print(f"  已移走 {skill}（等价于删掉提示词）")
    try:
        c = cli(repo, tmp / "s1", "ask", "add 是怎么实现的")
        ok_cli = c.returncode == 0 and "[问题]" in c.stdout
        print(f"  CLI      rc={c.returncode}  装配成功={ok_cli}")

        out1 = assemble(repo, tmp / "s1", "add 是怎么实现的")
        ok_svc = bool(out1.get("prompt"))
        print(f"  服务     ok={ok_svc}  tokens={out1.get('tokens')}")

        pl = plugin_calls(repo, [{"tool": "ctxfold_ask",
                                  "args": {"query": "add 是怎么实现的", "corpus": str(repo)}}])
        ok_pl = bool(pl.get("out")) and "[问题]" in pl["out"][0].get("text", "")
        print(f"  插件工具 已注册={pl.get('tools')}")
        print(f"           装配成功={ok_pl}")
        RESULTS["① 停用 Skill 后仍能运行（CLI/服务/插件）"] = ok_cli and ok_svc and ok_pl
    finally:
        if moved:
            shutil.move(str(backup), str(skill)); print("  已恢复 skill/")

    # ---------------- ② ----------------
    print()
    print("=" * 72)
    print("② 出处头格式 + 非 raw 项按 ID 取回（含文件改动后）")
    print("=" * 72)
    st2 = tmp / "s2"
    first = assemble(repo, st2, "total 是怎么实现的", budget=40)     # 小预算逼出 placeholder
    raw = first["raw_blocks"]
    print(f"  第一轮 raw {len(raw)} 个：{[b['header'] for b in raw]}")
    ok_header = bool(raw) and all(HEADER_RE.match(b["header"]) for b in raw) \
        and all(b["header"] in first["prompt"] for b in raw)

    second = assemble(repo, st2, "total 是怎么实现的", budget=40)
    non_raw = {c: lv for c, lv in second["levels"].items() if lv != "raw"}
    print(f"  第二轮 levels={second['levels']}")
    print(f"  非 raw 项（{len(non_raw)}）：{non_raw}")
    ok_recall = bool(non_raw)
    for cid, lv in list(non_raw.items())[:3]:
        r_cli = json.loads(cli(repo, st2, "recall", cid, "--json", budget=40).stdout)
        r_svc = service(repo, st2, [{"id": 1, "op": "recall", "args": {"cid": cid}},
                                    {"id": 2, "op": "close"}], budget=40)[0]["result"]
        r_pl = plugin_calls(repo, [{"tool": "ctxfold_recall", "args": {"cid": cid, "corpus": str(repo)}}])
        text_pl = r_pl["out"][0].get("text", "") if r_pl.get("out") else ""
        same = (r_cli["text"] == r_svc["text"]) and (r_cli["header"] in text_pl)
        ok_recall = ok_recall and same and bool(r_cli["text"])
        print(f"  {cid} ({lv}): 三通路一致={same} source={r_cli['source']} unchanged={r_cli['unchanged']}")

    # 改文件后再取回：应拿到当初那段（快照），并标记 unchanged=false
    probe_cid = next((c for c in non_raw if c.endswith("::add")), next(iter(non_raw)))
    old_text = json.loads(cli(repo, st2, "recall", probe_cid, "--json").stdout)["text"]
    (repo / "base.py").write_text("def add(a, b):\n    return a + b + 0\n    # changed\n", encoding="utf-8")
    after = json.loads(cli(repo, st2, "recall", probe_cid, "--json").stdout)
    stable = (after["text"] == old_text) and (after["unchanged"] is False) and (after["source"] == "snapshot")
    print(f"  改动后取回：仍是旧文本={after['text'] == old_text}  unchanged={after['unchanged']}  source={after['source']}")
    RESULTS["② 出处头 + 非 raw 项按 ID 稳定取回"] = ok_header and ok_recall and stable

    # ---------------- ③ ----------------
    print()
    print("=" * 72)
    print("③ 改符号 -> 结论失效 + 下游波及 + 其余复用")
    print("=" * 72)
    st3 = tmp / "s3"
    assemble(repo, st3, "add 是怎么实现的")
    assemble(repo, st3, "total 是怎么实现的")
    assemble(repo, st3, "unrelated 是怎么实现的")
    # 现在才改动 base.py，然后看失效面
    (repo / "base.py").write_text("def add(a, b):\n    return a + b + 1\n    # changed by step 3\n", encoding="utf-8")
    inv = json.loads(cli(repo, st3, "invalidate").stdout)
    print(f"  invalidated={inv['invalidated']}")
    print(f"  downstream ={inv['downstream']}")
    print(f"  kept       ={inv['kept']}")
    again = assemble(repo, st3, "add 是怎么实现的")
    reread = [b["cid"] for b in again["raw_blocks"]]
    unrelated = next((c for c in inv["kept"] if c.endswith("::unrelated")), "")
    ok3 = (any(c.endswith("::add") for c in inv["invalidated"])
           and any(c.endswith("::total") for c in inv["downstream"])
           and bool(unrelated) and unrelated not in reread)
    print(f"  改动后重读的 raw={reread}")
    print(f"  未改动符号被重发原文={unrelated in reread}（应为 False）")
    RESULTS["③ 失效传播 + 未改动复用"] = ok3

    print()
    print("=" * 72)
    for k, v in RESULTS.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print("=" * 72)
    print(json.dumps({"all_pass": all(RESULTS.values()), "details": RESULTS}, ensure_ascii=False))
    return 0 if all(RESULTS.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
