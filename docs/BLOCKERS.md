# 剩余缺口与解锁方式

> 更新于 2026-11-12。本文件只记两件事：**还差什么**，以及**差的东西怎么补**。
> 代码、离线实验、论文、发布物料均已完成（见 [附录 A](appendix-experiments.md) 与 `README.md`）。

---

## 一、在线实验 —— 状态：**已完成首轮**（2026-11-12）

已用 deepseek-chat 完成 90 次真实调用，结果见附录 A.14：
定位 1.000 / 依赖 gold 召回 0.845 / 语义 0.733 / H 0.322 / recall 0.567。
剩余工作：扩大样本、跨模型与跨仓库复现（见文末清单）。

以下为历史记录（如何确认"缺的只是 key"），保留以备复核。

### 附：当时的就绪检查结论 —— 状态：`NO_KEY`

这是唯一会影响论文结论强度的缺口。当前论文中所有准确率均来自**模拟推演**，不是真实数据。

### 已排除的原因（都实测过，不是猜测）

| 可能原因 | 实测结论 |
|---|---|
| 沙箱没有网络 | ❌ 排除了：arxiv / PyPI / 多个国内模型端点均可访问 |
| 端点不可达 | ❌ 排除了：`api.deepseek.com`、`open.bigmodel.cn`、`api.moonshot.cn`、`dashscope.aliyuncs.com` 均返回 401（服务器活着，只是没授权） |
| 可以用本地模型替代 | ❌ 不可行：`llama-cpp-python` 无预编译轮子；ollama 二进制下载被重定向到 github.com（本机不可达） |
| OpenAI 端点 | ⚠️ 本机不可达（`URLError`），需改用国内端点 |

### 现在就能验证的结论

```bash
python scripts/check_endpoint.py
# 输出：结果是 NO_KEY：网络可用，只差 API key。
```

### 解锁命令（三行环境变量 + 一条命令）

```bash
set CTXFOLD_BASE_URL=https://api.deepseek.com/v1
set CTXFOLD_API_KEY=sk-...
set CTXFOLD_MODEL=deepseek-chat
python scripts/check_endpoint.py          # 应输出 READY
python experiments/m3_online.py --mode real --tasks 30
```

### 会得到什么

| 指标 | 含义 | 现状 |
|---|---|---|
| A 正确率 | 端到端答对比例（题型分定位／依赖／语义） | 仅有模拟推演 |
| H 免算率 | 无需 recall 即答对的回合比例 | 未测 |
| recall 触发率 | 模型主动调用 `recall` 的回合比例 —— **决定本文主张能否成立的关键量** | 未测 |
| L 延迟 | 每轮 wall-clock p50/p95 | 未测 |
| 成本 | 实际花费（30 条任务约几元） | 未测 |

### 预算估计

30 条任务 × 3 种题型 ≈ 90 次调用，每次输入 2k–4k token。
以 deepseek-chat 量级计，**总成本约在几元人民币**。

---

## 二、GitHub 首发 —— 状态：需要 push 权限

仓库已具备发布条件（见 README 的发布门槛自检）：一条命令可复现、CI 已配、LICENSE 齐、demo 与自检脚本齐。
但**本机访问 github.com 不可达**，且本会话不代用户创建仓库或提交。

### 解锁方式（任选其一）

1. 用户在有网络的机器上：`git init && git add . && git commit -m "ctxfold v0.1" && git push`
2. 打包 `.zip` 交给用户手工上传
3. 换成可达的托管（Gitee / GitLab / 自建 Git）

提交前建议先跑一遍：

```bash
python scripts/selfcheck.py     # 文档/代码一致性 + RESULTS 新鲜度
python tests/test_core.py       # 15 条自测
python scripts/demo.py          # 30 秒演示
python scripts/robustness.py --limit 300
```

---

## 三、验收清单（外部条件满足后如何确认完成）

- [ ] `check_endpoint.py` 输出 `READY`
- [ ] `m3_online.py --mode real` 产出 `summary.json`，含 A / H / recall_rate / tokens_mean
- [ ] 把实测值回填论文 §5-RQ5、§7 威胁第 2 条，并删除"所有 A 均来自模拟推演"这句
- [ ] `RESULTS.md` 增加在线一节；`selfcheck` 仍全绿
- [ ] 仓库出现在 GitHub，README 顶部链接可达

---

## 四、不做什么

- 不伪造在线数据；没有 key 就不产出 A/H/E。
- 不用"本地小模型"顶替真实端点并当作论文数据（本机也拿不到可用引擎）。
- 不在没有用户明确指示的情况下创建仓库或提交。
