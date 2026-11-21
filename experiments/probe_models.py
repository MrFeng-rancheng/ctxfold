# -*- coding: utf-8 -*-
"""探测可用的模型端点（只打印模型名，不打印密钥）。"""
import json
import pathlib
import urllib.request

SEC = pathlib.Path(r"C:\Users\13956\.dsh\secrets")


def load(name):
    kv = {}
    p = SEC / name
    if not p.exists():
        return kv
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def probe(label, base, key, limit=40):
    print("=== %s (%s) key=%s" % (label, base, "有" if key else "无"))
    if not key:
        return
    try:
        req = urllib.request.Request(base.rstrip("/") + "/models",
                                     headers={"Authorization": "Bearer " + key})
        d = json.load(urllib.request.urlopen(req, timeout=25))
        ids = [m.get("id") for m in d.get("data", [])]
        print("  可用模型 %d 个" % len(ids))
        for i in ids[:limit]:
            print("   ", i)
    except Exception as e:
        print("  ERR", type(e).__name__, str(e)[:160])


sf = load("media-tools.env")
probe("SiliconFlow", "https://api.siliconflow.cn/v1", sf.get("SILICONFLOW_API_KEY", ""))
probe("SenseNova", "https://api.sensenova.cn/compatible-mode/v1", sf.get("SENSENOVA_API_KEY", ""))
ac = load("atlas-cloud.env")
probe("AtlasCloud", "https://api.atlascloud.ai/v1", ac.get("ATLASCLOUD_API_KEY", ""), limit=10)

# DSH 自带的 deepseek 配置在哪
for cand in [r"C:\Users\13956\.dsh\llm-deepseek", r"C:\Users\13956\.dsh\profiles\desktop"]:
    p = pathlib.Path(cand)
    if p.exists():
        print("=== 目录", cand)
        for f in list(p.rglob("*"))[:12]:
            print("   ", f.name, f.stat().st_size if f.is_file() else "<dir>")
