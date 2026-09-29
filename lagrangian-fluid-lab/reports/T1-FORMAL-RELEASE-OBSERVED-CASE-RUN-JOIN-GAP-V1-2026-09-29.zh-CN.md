# T1 formal release → observed case-run aggregate join gap

- 状态：`blocked_fail_closed`；join identity valid：`True`
- 固定目标分母：`0/432` observed；缺口：`432`
- formal：`false`；T1：`false`；credit：`0`；本报告不授权执行或计数。

## 已闭合的元数据连接

- 每个 formal model×seed run：`32` 个 F3 + `16` 个 F4 = `48` 行。
- F3/F4 总目标行：`288` / `144`；不复制既有 432 行 inventory。
- formal release 的 9 个 run ID 与 T1 projection 的 model/seed identity 一一对应。

## 仍然阻塞

- `FORMAL_RELEASE_ROOT_ADMISSION_NOT_READY`
- `EXTERNAL_ROOT_AUTHORITY_NOT_CONSUMABLE`
- `FORMAL_TERMINAL_EVIDENCE_NOT_COMPLETE`
- `NO_OBSERVED_T1_MODEL_CASE_RUN_RECEIPTS`
- `AGGREGATE_JOIN_IS_NON_AUTHORIZING`

## 边界

只读取有界 JSON 元数据；没有打开/重哈希 HDF5、checkpoint 或 trajectory，没有启动 trainer、solver、worker、GPU、queue，也没有修改 registry、ledger、denominator、gate、completion 或 PLAN。外部 scheduler/root authority 与 authority-bound terminal receipt 仍未被消费。
