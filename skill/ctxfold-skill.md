# ctxfold 使用提示（可选，可整目录删除）

> **这个文件不是运行所需。** 删掉整个 `skill/` 目录，核心状态机与装配逻辑照常工作——
> 因为逻辑在 `src/ctxfold/`（`state.py` 管状态、`assembler.py` 管装配、`service.py` 管接口），
> 不在任何提示词或会话约定里。本文件只是写给"想用自然语言指挥 agent"的人看的说明书。

## 你可以让 agent 做的事

| 你想说的 | agent 应该调的接口 |
|---|---|
| “看看这个仓库值不值得用” | `ctxfold doctor --corpus <path>` |
| “这段代码在哪、干什么” | `ctxfold ask "<问题>" --json` |
| “把 #calc.py::add 的原文给我” | `ctxfold recall calc.py::add` |
| “我刚改了代码，哪些结论不能用了” | `ctxfold invalidate` |
| “现在记住什么、哪些新鲜” | `ctxfold state` / `ctxfold status` |

## 如果宿主支持常驻服务

启动一次，之后按行发 JSON：

```bash
ctxfold --corpus /path/to/repo --state .ctxfold serve
```

```
{"id":1,"op":"assemble","args":{"query":"add 做了什么"}}
{"id":2,"op":"recall","args":{"cid":"base.py::add"}}
{"id":3,"op":"invalidate"}
```

## 三条不变式（由代码保证，不靠模型自觉）

1. 每个 raw 块都带出处头 `### #<cid> | <file>:<start>-<end>`；
2. 每个占位符都能用 `recall <cid>` 取回原文，哈希一致时 `unchanged=true`；
3. 改动某符号后 `invalidate` 会给出 `invalidated`（自身变了）与 `downstream`（依赖它的），
   其余仍在 `kept` 里继续复用。
