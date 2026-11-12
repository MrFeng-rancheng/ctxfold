# 贡献指南

## 这个项目最看重什么

不是功能多，是**数字可信**。任何 PR 的价值排序：

1. **让某个主张可复现** > 2. **让某个主张被证伪并如实记录** > 3. 新功能 > 4. 性能优化 > 5. 文档润色

如果你发现 README/论文里的某个数字复现不出来——**这是最高优先级的 issue**，请在标题写 `[repro]`。

## 提交前必跑

```bash
PYTHONPATH=src python tests/test_core.py          # 必须全绿
PYTHONPATH=src python experiments/reproduce.py     # 结果应与 experiments/RESULTS.md 同量级
```

如果改动会影响任何已发布的数字，请**在 PR 描述里列出旧值 → 新值**，并说明原因。
只改数字不说明原因的 PR 会被要求补充。

## 代码约定

- 只用标准库；新增第三方依赖需要说明为什么标准库做不到
- 指标计算与实验脚本分开：`src/` 只放机制，`experiments/` 只放测量
- 每个实验必须落盘 `summary.json` + `manifest`（commit、时间、tokenizer、seed、预算）
- 任何"估算值"必须在输出里显式标注是估算
- 新增机制必须同时给：**它提升了什么、它让什么变差了**

## 报告问题

请附上：`ctxfold status` 输出、复现命令、期望值与实际值。
如果涉及数字，请附 `experiments/runs/<id>/manifest.json`。

## 不要做的事

- 不要为了让指标好看而调整 gold 定义（这属于数据操纵）
- 不要声称"模型内部被加速"——本项目在系统层，必须明说
- 不要去掉 README 里的"局限"章节
