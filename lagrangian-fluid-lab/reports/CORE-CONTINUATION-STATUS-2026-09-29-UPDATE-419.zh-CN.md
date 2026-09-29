# Core continuation status — UPDATE-419

本轮按“尽快收尾、不再新开任务”的要求，只收尾已经启动的 F3 current-manifest hidden16 诊断批次；没有新增 subagent、没有启动新的 workload，也没有改写历史报告。当前 subagent 策略保持为 `gpt-5.6-luna`、reasoning `max`。

## F3 诊断批次

- seed17、seed29、seed43 各完成 `32/32` 个 current-manifest case，共 `96/96` 个 case×seed 组合。
- 共 `12` 个 fresh batch；每批 `8/8` case 为 `exited_successfully`，terminal receipt 完整，diagnostic/formal credit 均为 `0`。
- 最后一批 seed29 c16c23 已单独提交为 `fb91951d`；所有批次均未写入 formal registry、ledger、denominator 或 gate。

只读 rollup 汇总报告已提交为 `b5078f6e`。汇总目录保留历史诊断批次，因此观察到 `22` 份 batch report、唯一 case×seed 覆盖 `96/96`，但有 `63` 个历史重复 pair、`162` 行严格审计失败；工具状态仍为 `incomplete_diagnostic_rollup`、fully auditable rows=`0`、credit=`0`。这不改变任何正式 Core 状态，也不通过推断补齐严格证据字段。

## 当前 Core gate

只读状态仍为 `can_finalize=false`：T1 家族为 `F3/F4`，macro T2 为 `0` 个，formal training 为 `0/9`，observed T1 case-runs 为 `0`（注册目标缺 `288`、固定目标缺 `432`），observed material case-runs 为 `0`（固定目标缺 `288`），independent reproduction=false，credit=`0`。scheduler 当前 `queued=0、reserved=0、launching=0、running=0、attention=0、succeeded=294、failed=19、cancelled=13`。

真实 external scheduler authority/trusted key、F4 archives-v2 与 material sidecars、formal release/root/terminal receipts、F8 trusted target pins 以及 A8 trusted external-host/full-product receipts 仍缺失；本轮不再启动任何补充任务，继续保持 fail-closed。
