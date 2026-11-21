# m14 传播精度（自动生成，勿手改）

目标符号 `cookiejar.py::split_header_words`，1 跳结构失效集 |I| = 2；探针 8 个（单输入）。

| 改动 | 结构失效集 | 探针数 | 探针观测到变化 |
| --- | --- | --- | --- |
| 只加一行注释 | 2 | 8 | 0 |
| 改函数体返回空表 | 2 | 8 | 2 |

基准值：

- `strip_quotes` -> 'abc'
- `split_header_words` -> [[('a', 'b'), ('Path', '/'), ('HttpOnly', None)], [('x', 'y')]]
- `parse_ns_headers` -> [[('a', 'b'), ('path', '/'), ('version', '0')], [('c', 'd'), ('domain', '.e.com'), ('version', '0')]]
- `is_HDN` -> True
- `domain_match` -> True
- `join_header_words` -> ERR ValueError
- `parse_ns_headers_v2` -> [[('q', '1'), ('version', '1')]]
- `split_header_words_v2` -> [[('k', 'v'), ('flag', None)]]
