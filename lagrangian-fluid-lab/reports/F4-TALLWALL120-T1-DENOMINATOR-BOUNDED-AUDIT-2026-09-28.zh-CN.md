# F4 Tallwall120 T1 分母只读审计（2026-09-28）

结论：F4 Tallwall120 的 CFD reference 数据完整，当前缺口是模型/seed 的 evaluation receipts，不是 trajectory 数据。审计严格 `diagnostic_only`，没有填充正式分母，也没有修改 registry、ledger、gate 或历史 receipt。

## 结果

- qualified scope `F4_resting_pool_laminar_tallwall120_x_v1` 的 production qualification cases 为 `32/32`。
- 16 个 F4 evaluation cases 全部存在 trajectory、evidence、collection 和 registry identity：`DEV_00, DEV_01, DEV_02, DEV_05, DEV_08, DEV_09, DEV_13, DEV_14, DEV_17, DEV_18, DEV_22, DEV_23, DEV_26, DEV_29, DEV_30, DEV_31`。
- 每个 HDF5 的元数据结构通过；每例 218 frames，时间端点 `0–4.340002980805959 s`。只读取 metadata 与两个 time endpoint scalar，没有读取 state frames。
- 9 个 formal model/seed runs × 16 个 F4 evaluation cases，形成 F4 模型 case-run 缺口 `144`；当前两族合计 registered T1 缺口 `288`，target 缺口 `432`。其中 `144` 是第三个 T1 family 的目标容量，不是 Tallwall120 CFD 缺失。

## Fail-closed 边界

现有 F4 diagnostic profile 只绑定 1 个 train case 和 2 个 validation cases，不能填充正式 denominator；Core formal reader 仍要求尚未闭合的 V13 trusted-reader capability。因此本审计不启动 GPU、solver、worker、training 或 rollout，formal/T1/T2/credit 均保持 false/0。

原始审计 JSON 的 SHA-256 为 `66108f1ad1c53bf8a10ceb7c4efbeb273bb79fe2f20a67d857545b420fef71f2`；持久化摘要见同目录 JSON 报告。
