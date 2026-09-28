# F3 graph_raw hidden16 seed43 terminal completion receipt

状态：`bound_existing_terminal_summary`。本 receipt 只绑定既有 seed43 diagnostic full835 终态，不启动新的 evaluate。

## 终态 markers

- 模型：`graph_raw`，hidden=`16`，seed=`43`，updates=`500`。
- 终态：`835/835 transitions`、`836/836 frames`，validator=`True`。
- 结论仍为 diagnostic-only：formal/T1/T2/credit 不产生资格或积分。

## identity 绑定

- `training_receipt`：`/tmp/f3-graph-raw500-hidden16-seed43-20260928-training.json`，claimed bytes=`10662`，stat bytes=`10662`，content_opened=`True`，hash=`verified`。
- `evaluation_receipt`：`/tmp/f3-graph-raw500-hidden16-seed43-full835-20260928-evaluation.json`，claimed bytes=`6389198`，stat bytes=`6389198`，content_opened=`True`，hash=`verified`。
- `checkpoint`：`/tmp/f3-graph-raw500-hidden16-seed43-20260928-checkpoint.pt`，claimed bytes=`152081`，stat bytes=`152081`，content_opened=`False`，hash=`not_read_by_scope`。
- `trajectory`：`/tmp/f3-graph-raw500-hidden16-seed43-full835-20260928-trajectory.h5`，claimed bytes=`723148320`，stat bytes=`723148320`，content_opened=`False`，hash=`not_read_by_scope`。

## 安全边界

- 本 runner 未停止或重启 existing live job；未启动新的 evaluate；输出命名空间为空。
- progress、trajectory/HDF5、manifest、checkpoint 均未打开内容，仅对后者做 `lstat`/bytes 检查；training/evaluation JSON 仅用于 receipt SHA-256 核对。
- registry、ledger、denominator、gate mutation 均为 `0`；formal、T1、T2、qualification、credit 均不改变。
