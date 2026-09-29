# F3 MLP hidden16 current-manifest source-lineage blocker

日期：2026-09-29

结论：本轮不实施 intake 放宽或 hash 归一化，继续 `blocked_fail_closed`、`source_bound=false`、`credit=0`。UPDATE-390 暴露的是 producer/intake 契约缺口，同时也是必须保持拒绝的证据边界。

## 已核对的 drift

`5d53fd9c…c4f768` 与 `8d87da6a…e680` 不是同一字段的两个值：

- `5d53…` 是当前 manifest JSON payload 的 canonical SHA，current-manifest training producer 要求 receipt `config.manifest_sha256` 绑定它；
- `8d87…` 是 `campaigns/core-v1/f3-dataset-v2.json` 的 raw-file SHA，历史 full835 summary 使用它。

training matrix/history intake 当前直接比较两者，因而得到 `training matrix/history manifest source drift`。这不是可以通过修改旧 matrix 或旧 summary 消除的安全修复。

## 为什么不能接受旧 receipt

旧 training/terminal 记录属于 `20260928` generation；current-manifest producer 使用新的 current run identity，并且已经将 raw SHA 与 canonical SHA 分开记录。legacy fresh-terminal builder 没有显式的 current-manifest identity projection，也没有 typed hash-domain 字段。若把 raw SHA 自动映射成 canonical SHA，或仅因它们指向同一路径就放宽比较，就会丢失 producer-generation 边界，允许旧 receipt 冒充 current receipt。

安全的后续 producer contract 必须同时提供 `manifest_file_sha256`、`manifest_canonical_sha256`、current run/receipt/checkpoint/nonce 绑定和 terminal proof；在此之前拒绝是正确行为。

机器回执：[JSON blocker report](F3-MLP-HIDDEN16-CURRENT-MANIFEST-SOURCE-LINEAGE-BLOCKER-2026-09-29.json)。

## 回归与边界

- 定向 training-evidence + fresh-terminal：`42 passed`；
- 全部 `test_f3_mlp_hidden16_*.py`：`158 passed`；
- 新增回归锁定 raw-vs-canonical drift 不得被归一化；
- 未读取 checkpoint/trajectory/HDF5 等大型 live artifact，未启动 GPU/solver；未修改 raw/residual 或 Core registry、ledger、denominator、gates、completion。
