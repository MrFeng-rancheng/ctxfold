"""selfcheck：验证"文档说的"与"代码做的"是否一致。

检查五项：
  1. 结构：README 里列出的每个模块/文件真实存在；
  2. CLI：README 里出现的子命令在 cli.py 里真的有；
  3. 引用：docs 里提到的 experiments/*.py、docs/*.md 都存在；
  4. 测试：tests/test_core.py 通过；
  5. 结果新鲜度：重新跑 reproduce，生成的 RESULTS.md 与仓库里的**除时间戳外**逐行一致
     （不一致 = 文档里的数字已经落后于代码，这是最危险的一类漂移）。

用法：python scripts/selfcheck.py
失败时退出码 1。
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
FAILS: list[str] = []
WARNS: list[str] = []


def ok(msg: str) -> None:
    print(f"  [ok]   {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    FAILS.append(msg)


def warn(msg: str) -> None:
    print(f"  [warn] {msg}")
    WARNS.append(msg)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def check_structure() -> None:
    print("\n1) 结构")
    readme = read(ROOT / "README.md")
    mods = sorted(p.name for p in (ROOT / "src" / "ctxfold").glob("*.py") if p.name != "__init__.py")
    for m in mods:
        if m in readme:
            ok(f"{m} 在 README 中被提及")
        else:
            warn(f"{m} 未在 README 中出现（可能缺少说明）")
    for d in ("docs/design.md", "docs/protocol.md", "docs/roadmap.md", "docs/paper-draft.md"):
        if (ROOT / d).exists():
            ok(f"{d} 存在")
        else:
            fail(f"{d} 缺失")


def check_cli() -> None:
    print("\n2) CLI 子命令")
    cli_src = read(ROOT / "src" / "ctxfold" / "cli.py")
    declared = set(re.findall(r'sub\.add_parser\("([a-z_]+)"', cli_src))
    readme = read(ROOT / "README.md")
    used = set(re.findall(r"ctxfold\.cli[^\n]*?\b(init|ask|status|audit|doctor)\b", readme))
    ok(f"cli.py 声明: {sorted(declared)}")
    for u in sorted(used):
        if u in declared:
            ok(f"README 使用的子命令 {u} 已实现")
        else:
            fail(f"README 提到 {u}，但 cli.py 未实现")


def check_refs() -> None:
    print("\n3) 文档引用")
    docs = list((ROOT / "docs").glob("*.md")) + [ROOT / "README.md", ROOT / "CHANGELOG.md"]
    pat = re.compile(r"(experiments/[\w./-]+\.py|docs/[\w./-]+\.md|scripts/[\w./-]+\.py)")
    seen: set[str] = set()
    for d in docs:
        for ref in pat.findall(read(d)):
            if ref in seen:
                continue
            seen.add(ref)
            if (ROOT / ref).exists():
                ok(f"{ref} 存在")
            else:
                fail(f"{d.name} 引用了不存在的 {ref}")


def check_tests() -> None:
    print("\n4) 测试")
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([PY, "tests/test_core.py"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", env=env)
    if p.returncode == 0:
        ok(p.stdout.strip().splitlines()[-1])
    else:
        fail(f"tests 失败:\n{p.stdout[-800:]}{p.stderr[-800:]}")


def _strip_volatile(text: str) -> list[str]:
    """去掉生成时间与耗时行，其余逐行比较。"""
    out = []
    for line in text.splitlines():
        if line.startswith("生成时间："):
            continue
        out.append(line)
    return out


def check_freshness() -> None:
    print("\n5) 结果新鲜度（RESULTS.md 是否落后于代码）")
    target = ROOT / "experiments" / "RESULTS.md"
    if not target.exists():
        fail("RESULTS.md 不存在，请先跑 reproduce")
        return
    before = read(target)
    env = {"PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([PY, "experiments/reproduce.py"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", env=env)
    if p.returncode != 0:
        fail(f"reproduce 失败:\n{p.stderr[-800:]}")
        return
    after = read(target)
    a, b = _strip_volatile(before), _strip_volatile(after)
    if a == b:
        ok("RESULTS.md 与当前代码产出一致")
        return
    diffs = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y][:6]
    detail = "\n".join(f"    L{i}: 仓库={x[:80]!r}\n         复现={y[:80]!r}" for i, x, y in diffs)
    fail(f"RESULTS.md 与复现结果不一致（前几处）：\n{detail}\n（已用新结果覆盖仓库文件，请 review 后提交）")


def check_figures() -> None:
    """论文插图规范（对外部脚本的软依赖）：存在则必须全绿。"""
    print("\n6) 插图规范（纯灰度 / 无图内标题 / 无圆角 / 字号 >= 22px）")
    cand = [ROOT.parent / "paper_build" / "figure_check.py",
            pathlib.Path.home() / "Desktop" / "插件开发" / "paper_build" / "figure_check.py"]
    script = next((c for c in cand if c.exists()), None)
    if script is None:
        warn("未找到 figure_check.py（论文工程不在本机），跳过插图检查")
        return
    p = subprocess.run([PY, str(script)], capture_output=True, text=True, encoding="utf-8")
    tail = [ln for ln in (p.stdout or "").splitlines() if ln.startswith("[") or ln.strip().startswith("-")]
    if p.returncode == 0:
        ok("插图检查通过：" + "；".join(tail))
    else:
        fail("插图不符合期刊规范：\n" + "\n".join("    " + t for t in tail))


def main() -> int:
    print("ctxfold selfcheck")
    check_structure()
    check_cli()
    check_refs()
    check_tests()
    check_freshness()
    check_figures()

    print("\n" + "=" * 50)
    if FAILS:
        print(f"失败 {len(FAILS)} 项，警告 {len(WARNS)} 项")
        for f in FAILS:
            print("  -", f.splitlines()[0])
        return 1
    print(f"全部通过（警告 {len(WARNS)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
