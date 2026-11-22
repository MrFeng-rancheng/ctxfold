# 运行时接口：S = (C, G, D, L)

核心逻辑不在任何 Agent 的 Skill 提示词里，也不依赖会话约定。它就是一个本地模块，
任何宿主（CLI、DSH 插件、MCP 桥、自研 agent）用同一组接口调用。

- 状态机：`src/ctxfold/state.py` → `StateRuntime`
- 装配器：`src/ctxfold/assembler.py`（纯函数，无状态）
- 服务接口：`src/ctxfold/service.py`（stdio 上的行 JSON）
- 提示词：`skill/ctxfold-skill.md`，**可选、可整目录删除**，核心不读它

## 状态四元组

| 分量 | 含义 | 来源 |
|---|---|---|
| `C` | 已验证结论：`cid -> {claim, verifier}` | `commit()` 写入 |
| `G` | 守卫条件：`cid -> {chunk_sha, file_sha, status}` | 固化时记录，`invalidate()` 更新 |
| `D` | 1 跳依赖闭包：`cid -> [它调用的 cid]` | 语法树解析（`resolve_dependencies`） |
| `L` | 表示层级：`cid -> raw / card / claim / placeholder` | 最近一轮 `assemble()` 写入 |

`ctxfold state` 直接打印这四元组与计数。

## 两种调用方式

### 1) 命令行（一次性）

```bash
ctxfold --corpus /repo --state .ctxfold ask "add 是怎么实现的" --json
ctxfold --corpus /repo --state .ctxfold recall base.py::add
ctxfold --corpus /repo --state .ctxfold invalidate
ctxfold --corpus /repo --state .ctxfold state
```

### 2) 常驻服务（stdio，一行一个 JSON）

```bash
ctxfold --corpus /repo --state .ctxfold serve
```

| op | args | 返回 |
|---|---|---|
| `assemble` | `{"query": "..."}` | `prompt` / `tokens` / `raw_blocks` / `placeholders` / `levels` |
| `recall` | `{"cid": "..."}` | `text` / `path` / `start` / `end` / `unchanged` |
| `commit` | `{"cid","claim","verifier"?}` | `committed` |
| `invalidate` | — | `invalidated` / `downstream` / `kept` |
| `snapshot` | — | 四元组与计数 |
| `status` | — | 运行状态 + 层级表 |

任何语言都能调：请求是一行 JSON，响应也是一行 JSON，出错只影响那一条。

## 三条由代码保证的不变式

1. **出处头**：每个进入 prompt 的原文块形如 `### #base.py::add | base.py:1-2`，
   格式由 `assembler.assemble()` 生成，测试用正则校验。
2. **按 ID 取回**：`recall(cid)` 对占位符同样有效，返回原文 + 出处头 +
   `unchanged`（存储哈希与当前哈希是否一致）。
3. **失效与复用**：`invalidate()` 重新读盘、按符号哈希判定，
   返回 `invalidated`（自身变了）、`downstream`（依赖它的，1 跳）、`kept`（继续复用）。

## 怎么验证这三条

```bash
python tests/test_runtime_contract.py      # pytest，三条契约各一个用例
python scripts/verify_contract_demo.py     # 不需要 pytest，打印人能读的证据
```

`verify_contract_demo.py` 会做一件关键的事：**把 `skill/` 目录整个移走**，
再跑装配，证明核心不依赖提示词；然后改一个符号，打印
`invalidated` / `downstream` / `kept` 三组真实输出。
