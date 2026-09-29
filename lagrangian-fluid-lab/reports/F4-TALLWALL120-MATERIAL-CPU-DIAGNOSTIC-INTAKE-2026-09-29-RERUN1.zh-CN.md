# F4 Tallwall120 material CPU diagnostic intake / readiness

- 类型：`diagnostic_intake_readiness`（不是 receipt、不是 launch authorization）
- 状态：`blocked_before_execution`
- 代表案例：`F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`

## 选择与结论

选择 DEV_07 作为 F4 material/T2 RERUN3 的代表案例。已有 diagnostic JSON 可读，但只是历史 diagnostic-only 负结果：
`218 frames`、event window complete=`False`、unknown fraction max=`1.0`、common reliable coverage=`0.0`。
因此本轮在执行前被安全入口阻断，没有把历史结果伪造成 fresh receipt，也没有打开生产 HDF5 内容。

## 当前 prerequisite

- fresh-root receipt：present=`False`
- scheduler-owned host-I/O reservation：present=`False`
- fresh terminal / case sidecar：`False` / `False`
- sidecar matrix：missing=`32` / expected=`32`
- launch admitted：`False`

## 入口绑定

当前 `core_runtime`、F4 material CPU entry、case-sidecar intake 与 terminal-evidence intake 均做了有界源码绑定；这些入口本身不铸造 authority。
- core_runtime contract：`True`
- material entry contract：`True`
- sidecar entry contract：`True`
- terminal entry contract：`True`

## 阻塞原因

- `fresh_root_receipt_missing_or_invalid`
- `scheduler_owned_host_io_reservation_missing_or_invalid`
- `fresh_terminal_evidence_missing_or_incomplete`
- `DEV_07_material_case_sidecar_missing`
- `material_sidecar_matrix_incomplete`
- `archive_reader_source_identity_drift`

## 执行边界

计划模式为 CPU-only、q=0.5、dp=0.0075、512 seeds、2 substeps、baseline24；由于 prerequisite 未闭合，`executed=false`。
没有启动 solver/worker/native/GPU/queue，没有创建 fresh namespace 或写 material sidecar，没有改 registry/ledger/denominator/gate/completion/PLAN。

## 下一步

仅在外部 producer 提供当前 source-bound、one-use fresh-root receipt 与 scheduler-owned host-I/O reservation，且 terminal event window/DEV_07 sidecar/source-reader identity 完整后，重新运行 intake；随后才可由受控入口执行 CPU-only diagnostic。
