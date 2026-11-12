# ctxfold 快速开始（5 分钟）

不用读论文，也不用模型、不用网络。装完就能看到「同一段上下文，第二轮少付 token」。

## 1. 安装

```bash
pip install "ctxfold-0.1.0.zip"     # 或用仓库根：pip install .
ctxfold --help
```

只用标准库。想换更准的 token 计数再装可选依赖：`pip install ".[exact-tokens]"`（cl100k_base 分词器）。

## 2. 体检：这个仓库值不值得用

```bash
ctxfold doctor --corpus /path/to/your/repo
```

输出会直接给结论（划算 / 不划算）与建议预算、是否开 `--strict`。
判据是仓库的**跨文件引用密度**：模块互相引用越密，越值得用；单文件小脚本不值。

## 3. 建立状态并问第一个问题

```bash
ctxfold init --corpus /path/to/your/repo --state .ctxfold
ctxfold ask  --corpus /path/to/your/repo --state .ctxfold "process_order 是怎么工作的？"
```

`ask` **不调用模型**，它只产出「将要发给模型的那一轮 prompt」。你会看到：

- `### #src/order.py::OrderService.process_order | src/order.py:41-88` —— 每段原文都带出处头，行号可核对；
- 顶部的 token 计数与 `raw / card / placeholder` 明细。

## 4. 再问一次（省钱发生在这里）

```bash
ctxfold ask --corpus /path/to/your/repo --state .ctxfold "process_order 是怎么工作的？"
```

同一个问题第二次问，已固化内容变成**摘要卡**与**占位符**，原文不再重发；
模型若需要逐字原文，可以按 id 召回（`ctxfold ask --json` 里的 messages 就是标准 OpenAI 格式）。

## 5. 改一行代码，看它只失效一小块

```bash
# 改掉某个被依赖的函数后再问
ctxfold status --corpus /path/to/your/repo --state .ctxfold
```

理想输出是「只 stale 了被改的符号及其下游」，而不是整库重算。这就是选择性重算。

## 6. 审查场景：要逐字可见

```bash
ctxfold ask --corpus /path/to/your/repo --state .ctxfold --strict "…"
```

`--strict` 下已固化内容也重发原文：token 变多、严格可见率变高。这是一个显式旋钮，不是「更好」。

## 7. 复现论文数字

```bash
python experiments/reproduce.py      # 约 3 秒，重写 experiments/RESULTS.md
python scripts/demo.py               # 三函数小仓库四轮演示
python scripts/selfcheck.py          # 文档/代码一致性自检，必须全绿
```

## 常见问题

**Q：一定要有模型吗？**
装配不需要。只有当你要模型「自己决定读哪段代码」时才需要接一个 OpenAI 兼容端点（写 `.secrets.env`，不入库）。

**Q：能替代 KV cache 吗？**
不能，两层东西。KV cache 缓存 token 的中间张量、要求输入逐字相同；ctxfold 缓存结论与其成立前提、工作在应用层。

**Q：短对话有用吗？**
没有。判据是「同一个结论会被重复推导多少次」，通常要 10 轮以上才回本。

**Q：会不会把代码埋掉、模型看不见？**
不会。移出的内容一律可召回，且每条都记账，`ctxfold audit` 可查。
