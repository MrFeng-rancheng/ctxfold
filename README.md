# ctxfold

**把 AI 的上下文从"越堆越长的文本"变成"越用越准的状态"——让算力只花在未决的地方。**

> 状态：`v0.1.0` —— 离线实验全量可复现；在线实验**已小规模完成**（单模型 70 题），
> 规模与任务构造的局限已写在正文与 [局限](#局限) 里，不夸大。

## 主张（可反驳）

> 在代码 Agent 的多轮会话中，把上下文从"重演历史"改为"维护带守卫的结论状态"，
> 可以在不降低证据可得性的前提下把输入 token 降低 **47%–93%**；
> 代价是把"当场可见"换成"按需取回"，因此收益与模型主动取回（recall）的倾向强相关。

**它在什么情况下是错的**（都可测，详见 [docs/paper-draft.md](docs/paper-draft.md) §0）：

- 模型几乎不 recall，且任务以语义类问题为主 → 收益归零（模拟推演：语义类在 p=0 时准确率为 0）
- 世界变化太快、结论频繁失效 → 重算开销吃掉节省
- 装配与自校验开销超过节省 → 净收益为负（世界指纹在 2000+ 文件仓库上 261ms/轮）

**我们不主张**：模型变聪明、准确率提升、能替代 KV 缓存或检索、短对话有收益。

## 一句话

现在的代码 Agent 每一轮都在把同样的事重想一遍：历史全量重发、已经确定的结论重新推导。
ctxfold 给它一台**有状态的思考运行时**：结论一旦被验证就固化成带守卫条件的记忆，前提不变则零计算直接取用；前提一变则精确失效，只重算受污染的那一小块。

## 三个不变式

1. **无损**：移出上下文的内容不销毁，存原文 + ID + 行号，模型可随时 `recall(id)` 取回逐字原文，而不是摘要。
2. **可失效**：每条记忆必须携带机器可判定的守卫条件（guard）。写不出 guard 的结论不得固化。
3. **可回退**：所有 commit / stale / reuse / audit 写 append-only 账本，可回放任意时刻状态、可截断回退。

## 快速开始（纯 CPU，无需模型、无需网络）

只有 5 分钟？直接看 **[docs/quickstart.md](docs/quickstart.md)**；
想读代码：**[examples/minimal.py](examples/minimal.py)**（30 行，跑出「第二轮 token 下降」）。

```bash
pip install -e .        # 实测可用：装完得到 ctxfold 命令（Linux/macOS 同）
                       # 也可以不装，直接 PYTHONPATH=src python -m ctxfold.cli
ctxfold --corpus /path/to/repo --state .ctxfold ask "process_order 是怎么工作的？"
python scripts/selfcheck.py         # 文档/代码一致性自检（含 RESULTS.md 新鲜度）
export PYTHONPATH=src

# 1) 装配一轮上下文（不调用模型，只打印"将要发什么"）
python -m ctxfold.cli --corpus /path/to/repo --state .ctxfold ask "process_order 是怎么工作的？"

# 2) 再问一次 —— 已固化的依赖变成占位符，零原文输入
python -m ctxfold.cli --corpus /path/to/repo --state .ctxfold ask "process_order 是怎么工作的？"

# 3) 可见性优先（改代码 / 审查场景）：已固化内容也重发原文
python -m ctxfold.cli --corpus /path/to/repo --state .ctxfold --strict ask "process_order 是怎么工作的？"

# 4) 采用前先体检：这个仓库适不适合 ctxfold
python -m ctxfold.cli --corpus /path/to/repo --state .ctxfold doctor

# 5) 看看状态 / 静态抽检
python -m ctxfold.cli --corpus /path/to/repo --state .ctxfold status
python -m ctxfold.cli --corpus /path/to/repo --state .ctxfold audit
```

`ask --json` 输出标准 `messages` 数组，交给任意 OpenAI 兼容客户端即可（模型无关性的落地方式）。

### 一分钟 demo（`python scripts/demo.py`，本机实测）

在临时目录建一个 3 函数仓库，自动跑四轮：

| 动作 | 发出 token | 行为 |
|---|---|---|
| 第 1 次问 `process_order` | **94** | `raw=3`：读入自身 + 2 个依赖原文 |
| 第 2 次问同一问题 | **76** | `card=1 placeholder=2`：本符号变摘要卡，依赖变占位符 |
| 改掉 `validate()` 再问 | **94** | `stale_now=1 raw=1 card=1`：**只重读被改的那一个** |
| 第 4 次问（状态已追上） | 更小 | 全部卡片/占位符，零原文 |

第三、四行是这套东西的全部意义：**改一个函数，不会让整个记忆陪葬；也不会反复重读同一段代码。**

## 实验结果

全部离线、无需网络，一条命令复现：

```bash
python scripts/selftest_online.py   # 零成本验证在线实验全链路（本地假端点）
python experiments/reproduce.py     # 约 3 秒，产出 experiments/RESULTS.md
python experiments/m3_online.py --mode mock   # 按题型分层的收益分析（模拟，非数据）
```

**E1 五种上下文策略（50 轮，时间局部性 + 40% 长程引用）**

| 方法 | 总 token | 含全量 recall | C_cum | R_prompt | R_avail | 长程引用 R | 末轮 token |
|---|---|---|---|---|---|---|---|
| full（全量） | 271,982 | 271,982 | 0 | 0.717 | 0.717 | 0.751 | 9,693 |
| window-5 | 57,572 | 57,572 | 0.788 | 0.578 | 0.578 | 0.376 | 461 |
| summary（抽取摘要） | 43,583 | 43,583 | 0.840 | 0.561 | 0.561 | 0.376 | 1,407 |
| grep-RAG（BM25） | 43,528 | 43,528 | 0.840 | **0.702** | 0.702 | **0.731** | 847 |
| **ctxfold** | **23,670** | 56,351 | **0.913** | 0.626 | **1.000** | 0.429 | **127** |

读法（两句都说，不挑好看的）：

> ⚠️ **R_avail = 1.000 是定义决定的**：gold 由依赖图生成，闭包也按同一张图展开，
> 所以 gold ⊆ 闭包恒成立，未给原文的项又都会变成可 recall 的占位符——必然满分，方差为零。
> **这是自证结构，不是性能。** 有信息量的是 R_prompt 与 token 成本。多种子方差见 [experiments/SEEDS.md](experiments/SEEDS.md)。

- **成本**：23,670 token，是 grep-RAG 的 **54%**（严格可见证据率 0.626 vs 0.702，仍略低）。
- **可得性**：可召回证据率 **1.000**，即所有 gold 证据要么在 prompt 里、要么一条 recall 就能拿到。
- **最坏情况**：若模型把每个占位符都召回，成本升到 56,351（比 grep-RAG 高 29%）——这是必须承认的上限。
- **长程引用仍是软肋**：0.429 vs grep-RAG 0.731。原因很朴素：BM25 直接在**全库**检索，
  本来就不需要"记住"；而我们把已知证据换成了占位符。

**这就是本方法的真实边界**：它买的不是"证据更多"，是"同样的证据边界下更便宜"，以及在模型会 recall 时的覆盖优势。

**在线实验（deepseek-chat，小样本，单模型）**

三次独立运行共 210 次调用。这是唯一能裁决"模型到底会不会用"的证据：

| 语料 | n | 准确率 | 免算率 | 主动取回率 | 定位题 | 依赖题召回 | 语义题 |
|---|---|---|---|---|---|---|---|
| 标准库 http | 30 | 0.622 | 0.322 | 0.567 | 1.000 | 0.845 | 0.733 |
| 标准库 http（换种子） | 30 | 0.656 | 0.322 | 0.567 | 1.000 | 0.947 | 0.833 |
| 本项目源码 | 10 | 0.567 | 0.333 | 0.633 | 1.000 | 1.000 | 0.700 |

- **错误残留率 E = 0.417**（n=12）：让模型为代码写一条可执行断言、再由外部真实执行，约四成结论经不起它自己给出的检查。这就是"结论必须过校验器才准固化"的实证依据。
- **必须承认**：样本仅 70 题、单一模型、任务为合成构造。这些数字只说明机制在该构造下跑得通，不能外推到真实开发会话。
- 一个离线指标完全看不见的坑：首轮定位题准确率为 0，原因是原文块缺文件名与行号；补上出处头后由 0 变 1.000。过程指标替代不了端到端检验。

**其他实验**

| 实验 | 关键数字 |
|---|---|
| E2 guard 粒度（改 3 个符号） | 文件级误失效 **17 条 = 记忆的 70.8%**，重算成本 **3.1×** 于符号级 |
| E3 选择性重算 | 只重算「受影响项 + 下游」比重算全部省 **87.5–95.0%** |
| E4 等精度切片 | grep-RAG 预算加到 **19,200**（花 261,451 token）时证据率封顶 **0.802**，未达 ctxfold 的 1.000 |
| 负面结果 | `hops=2` 闭包使 R_prompt 0.498→0.407、成本 +10%（**默认 hops=1**） |
| chunker 修正 | 同名遮蔽（`__init__` 等）致 13.7% 检索指错对象 → 限定名修复后 R_avail 0.878→**1.000**；类整块重复计数致成本虚高 46% → 只切叶子 |
| 鲁棒性（整个 Python 标准库） | **2,213 个文件、37,149 个符号，零异常**；357 个文件无符号（全部是"合法但无可切符号"，无一处语法/编码错误）；50 次装配演练零失败；10.4 秒 |
| `doctor` 体检 | 两个语料给出相反建议且与实测一致：stdlib/http（跨文件边 5.5%）→ 默认配置即可（strict 仅多 22% 成本换 14 点）；本项目 src（跨文件边 45.7%）→ **建议开 --strict**（不开会损失 54% 严格可见率） |
| 跨语料复现（本项目自身源码） | 方向一致、幅度不同：C=0.882（省 88%），R_prompt 0.472 vs grep-RAG 0.661（**本仓库上劣势更大，因为模块互相引用密集**） |
| 消融（E5） | −closure 省 37% token 但可召回率 1.000→0.705；−placeholder 多花 41% 换回 **31 个点**严格可见率（显式旋钮）；card/claim 在过程指标下**不可见** |
| 结论层（`m6_claims.py`） | 同一符号三种表示：tiny 原文 17 / 卡 32 / 结论 24；bulky 原文 257 / 卡 57 / 结论 68。**结论的价值不是省 token，而是省一次推理**（card/raw 省「字」，claim 省「想」） |
| 动态抽检（`m5_verify.py`） | 2 条结论含 1 条故意写错 → **E = 0.5**，错的标 stale、对的保持 fresh；每次校验 ~34ms。边界：只有能写出可执行校验器的结论才适用 |
| 世界指纹（2213 文件） | 廉价门 261ms vs 内容指纹 447ms，每轮省 185ms；**但指纹本身已超过装配开销两个数量级**，故默认 `gate_interval` 节流，大仓库建议 5–10 |
| 摘要卡 | 占位符从"只有 id"升级为"id + 位置 + 签名 + 被调用名"：模拟推演中 p=0（模型从不 recall）时准确率 **0.428→0.867**，成本仅 +7% |

**E4 的自证风险（必须一起读）**：gold 由 AST 依赖图生成，而 ctxfold 用的正是同一张图，
所以"grep-RAG 追不上"部分是指标定义决定的——这是循环论证风险，不能当作独立证据。
真正的裁决只能来自在线实验（模型答对率）。

指标定义见 [docs/protocol.md](docs/protocol.md)（预注册，含修订记录）。
每个数字的来源、设置与复现命令见 [docs/appendix-experiments.md](docs/appendix-experiments.md)。

## 明确不做（v0.1 非目标）

多仓库、跨会话长期记忆、多角色分工、自主策略学习、向量检索、GUI、任何形式的模型微调。

拒绝向量库是有意的：代码域 `grep + AST 符号表` 更准、更可解释、零成本、零调参。

## 发布包

```bash
python scripts/package.py     # 生成 dist/ctxfold-0.0.1.zip + sha256 + manifest
```

已排除 `.git` / `__pycache__` / `experiments/runs` / `.secrets.env`。
**验证方式**：解压到任意目录后，在副本里跑 `tests/test_core.py`、`scripts/selfcheck.py`、
`scripts/demo.py`、`experiments/reproduce.py` 全部通过，且 `RESULTS.md` 与仓库版逐行一致——
即结果可跨环境复现，不是只在本机成立。

## 还差什么

两件事，都需要外部条件：[docs/BLOCKERS.md](docs/BLOCKERS.md)（含实测证据与解锁命令）。

```bash
python scripts/check_endpoint.py   # 现在的结果：NO_KEY（网络可用，只差 API key）
```

- **在线实验已完成三次**（共 210 次调用，两个 seed + 两个语料，见 A.14），结果稳定；
  但仍为单模型（deepseek-chat）、中小规模，跨模型复现待做。
- **GitHub 首发待 push**：本机访问 github.com 不可达；发布包已就绪。

## 局限

- **token 数是估算**（`chars/3.5`，零依赖、跨环境确定）。实测偏差（附录 A.13）：代码文本上**系统性高估约 30%**，
  故所有绝对 token 数应视为上界；但 C/R 这类比值只差 1.35 个百分点。
  需要精确值时设 `CTXFOLD_TOKENIZER=exact` 并安装 tiktoken。
- **A（正确率）、H（真免算率）、E（在线错误残留率）尚未测量**——它们需要真实模型调用，是下一阶段工作。
- **静态抽检只能发现"世界变了"，发现不了"当初就推错了"**。后者只能靠在线抽检与用户反馈。
- **R_prompt 会惩罚好行为**：越成功地固化证据，严格指标越低，故同时报 R_avail / R_eff（见协议）。
- 传播的污染闭包依赖 1-hop 稀疏依赖图，真实跨工程依赖更密，传播成本会上升。
- 在短对话、单轮问答场景**没有任何收益**，甚至略亏索引开销。

## 结构

```
src/ctxfold/
  chunker.py     符号级切块（AST）、文件/符号指纹、按序调用名、跨文件 import 解析
  assembler.py   闭包装配、预算感知、四层表示（原文/结论/卡片/占位符）、guard 判定、ablate 开关
  runtime.py     会话状态机（记忆 + 历史 + 账本 + 抽检 + 世界指纹门 + strict_visibility）
  ledger.py      append-only 账本（replay / rollback_to）
  audit.py       确定性抽检与 E 统计（无数据时返回 None，不谎报 0）
  world.py       世界指纹：cheap（mtime+size）门 / content 指纹 / git HEAD
  retrieve.py    BM25 词法检索（基线用；不做向量）
  tasks.py       可复现的任务序列生成（局部性 / 长程引用）
  tokenize.py    tokenizer 适配（tiktoken 或字符估算，估算时显式标注）
  llm.py         零依赖 OpenAI 兼容客户端（支持 function calling，供在线实验）
  doctor.py      采用前诊断：依赖密度、模拟节省与可见率损失、建议预算/是否 strict
  cli.py         命令行（init / ask / status / audit / doctor）
experiments/     离线实验与一键复现（reproduce.py / m3_online.py / m5–m7 …）
scripts/         demo.py（30 秒演示）、selfcheck.py（文档/代码一致性自检）、robustness.py（真实代码鲁棒性扫测）
docs/            设计、预注册协议、路线图、论文草稿
notes/           逐日实验笔记（论文素材）
tests/           自测（python tests/test_core.py）
```

## 许可

MIT，见 [LICENSE](LICENSE)。
