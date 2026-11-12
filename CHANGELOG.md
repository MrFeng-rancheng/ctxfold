# CHANGELOG

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号用语义化版本。

## [0.1.0] — 2026-11-13

首个准备公开发布的版本（此前 0.0.1 为内部可运行版）。本版只做"能交出去"需要的事，不动核心算法。

### Added
- `docs/quickstart.md`：5 分钟上手（体检 → 建状态 → 问两轮 → 改一行看选择性重算 → 复现论文数字）
- `examples/minimal.py`：30 行示例，跑出"第 1 轮 112 token / 第 2 轮 71 token"，不联网、不调用模型
- README 新增**在线实验结果**小节：三次独立运行 210 次调用（deepseek-chat），含准确率、免算率、
  主动取回率与错误残留率 E=0.417，并写明样本仅 70 题、单模型、合成任务的局限
- README 状态行改为如实描述：离线全量可复现 + 在线小规模完成

### Changed
- 版本号 0.0.1 → 0.1.0（`pyproject.toml`、`__version__`、`scripts/package.py` 三处对齐）

### Known limits
- 在线实验单模型、小样本；真实开发会话未验证
- `R_avail` 恒为 1.000 属定义使然（gold 与闭包同源），不作为性能主张
- token 数为字符估算，绝对值约高估 30%，比值指标不受影响

## [0.0.1] — 2026-11-12

首个可公开版本。**定位：离线可验证的上下文装配运行时**（不做模型加速宣传）。

### Added
- 符号级 AST 切块（限定名 `Class.method`、文件哈希、符号哈希、按源码顺序的调用名）
- 依赖闭包装配：命中优先 + 预算感知排序 + 占位符/未加载降级
- 摘要卡：已固化的被点名符号内联为 `#id | path:lines | 签名 | calls`
- 世界指纹（`world.py`）：cheap（mtime/size）门只用于跳过全库重读，content 指纹用于准确判定；
  Runtime 按 `gate_interval` 节流（大仓库实测每轮 261ms，必须节流）
- guard 双粒度：`symbol`（默认）/ `file`，支持失效判定与传播
- append-only 账本：`commit / stale / suspect / revive / reuse / recall / audit`，支持 `replay` 与 `rollback_to`
- 确定性抽检（`hash(cid+salt)`），E 无数据时返回 `None` 而不谎报 0
- **结论层**：`Runtime.remember(cid, claim, verifier)` 把天然语言结论与**可执行校验器**一起固化
- **动态抽检**：校验器存在时抽中即真跑（subprocess，超时 30s），能发现"代码没变但当初推错了"；
  没有校验器则退回静态哈希校验（发现不了推错）。实验 `experiments/m5_verify.py`
- **结论层进入装配**：primary 命中且已固化且带 `claim` 时，直接输出「已验证结论」块，
  而不是原文/卡片（实测：不更省 token，但省一次推理）
- 抽检接入 `Runtime.ask`：静态校验走**按需单文件重切**（不依赖节流门留下的旧快照）；
  并给出时延分析——静态抽检检出漂移慢于指纹门，其价值在动态验证器
- `strict_visibility` 配置（CLI `--strict`）：可见性优先，已固化内容也重发原文
- `ctxfold doctor`：采用前诊断（依赖密度、模拟 C 与严格可见率损失、建议预算与是否开 strict）
- CLI：`ctxfold init / ask / status / audit / doctor`，`ask --json` 输出标准 messages
- 模型客户端：零依赖 urllib，任何 OpenAI 兼容端点，支持 function calling
- 离线实验 5 组 + 一键复现 `python experiments/reproduce.py`（约 3 秒）
- 在线实验装置 `experiments/m3_online.py`（mock 推演 / real 真实调用两种模式）
- 9 条核心自测 `python tests/test_core.py`
- tokenizer 默认改为字符估算器（零依赖、跨环境确定性）；`CTXFOLD_TOKENIZER=exact` 切换 tiktoken
- `scripts/package.py`：生成发布包（zip + sha256 + manifest），自动排除凭据与原始 run
- `scripts/stub_server.py` + `scripts/selftest_online.py`：本地假 OpenAI 端点，
  零成本验证 `--mode real` 全链路（HTTP、function calling 的 recall 往返、usage 记账、分题型统计、不泄漏 key）
- `scripts/check_endpoint.py`：在线实验就绪检查（READY / NO_KEY / UNREACH），实测端点连通性且不打印密钥
- `docs/BLOCKERS.md`：剩余缺口、已排除原因、解锁命令与验收清单
- `scripts/calibrate_tokenizer.py`：实测估算器偏差（代码文本上高估约 30%，但比值类指标仅差 1.35 个百分点）
- `scripts/robustness.py`：拿整个 Python 标准库（2,213 文件 / 37,149 符号）做鲁棒性扫测，零异常；
  并区分"合法但无可切符号"与"语法/编码错误"，避免静默丢数据
- `scripts/selfcheck.py`：文档与代码一致性自检（模块/CLI/引用/测试/**RESULTS.md 新鲜度**）
- CI（GitHub Actions）：selfcheck + 测试 + 复现 + 结果产物

### Verified
- `pip install -e .` 实装验证：安装后 `ctxfold` 命令可用，`--help / doctor / ask` 在空目录（无 PYTHONPATH）下跑通；
  第二轮装配 125 → 73 token 且 `免算=True`

### Fixed
- 同名符号遮蔽：`__init__` / `read` 等重名导致 13.7% 检索指错对象 → 限定名 + 多候选索引 + 歧义降级
- 类整块与嵌套函数重复计数：同一段源码被算进多个块，成本虚高 46% → 只切叶子
- `BM25.top_k` 预算不足时 `continue` 导致偏向短小无关片段 → 改为 `break`
- 依赖解析按字母序取 top-3 的隐性偏置 → 按源码出现顺序
- `doctor` 在小仓库上显示"省 -120%"（负数节省）→ 改为"不划算（多 X%）"并加"仓库过小，诊断不稳定"提示
- 依赖解析同名撞车 → 同文件 > 同类前缀 > 全局首个

### Known limitations
- token 计数默认是估算（`chars/3.5`）；装 `[exact-tokens]` 后改用 cl100k_base
- A（正确率）、H（真免算率）、E（在线错误残留率）尚未在真实模型上测量
- 静态抽检只能发现"世界变了"，发现不了"当初推错了"
- R_prompt 会系统性惩罚"把已知证据固化为占位符"这一正确行为，故同时报 R_avail
- 长程引用在严格可见指标上低于 BM25 检索（设计性代价，非缺陷）
