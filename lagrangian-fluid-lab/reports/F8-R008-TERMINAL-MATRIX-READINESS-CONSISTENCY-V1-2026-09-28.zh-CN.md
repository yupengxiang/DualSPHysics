# F8/R008 terminal matrix ↔ readiness/handoff consistency bridge V1

- 状态：`diagnostic_only_terminal_matrix_readiness_consistency_blocked`
- scope：`F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R008`
- 固定矩阵：15/15 行，case-id 与 q 映射精确绑定。
- target/readiness：`diagnostic_only_target_kernel_readiness_blocked`；readiness/T1/formal 均为 `false`，credit 为 `0`。
- trusted issuer→worker→runtime：只绑定 synthetic contract projection；production identity、runtime measurement 与 execution authority 均为 `false`。
- attempt/nonce/terminal projection：`present=False`、attempt 数量 `0`、nonce markers bound=`False`、terminal markers bound=`False`。
- fail-closed blockers：attempt_evidence_missing、attempt_nonce_markers_missing、terminal_markers_missing
- mutation：completion/denominator/gate/ledger/plan/registry 全部为 `0`。

本 bridge 只读取 bounded strict JSON 和小文件元数据；不读取 production BI4/HDF5/solver frames，不执行 privileged probe、fanotify/kernel/native/solver/worker/GPU/queue，也不写 registry、ledger、denominator、gate、completion 或 PLAN。`build_report()` 是该机器报告的唯一重算来源。
