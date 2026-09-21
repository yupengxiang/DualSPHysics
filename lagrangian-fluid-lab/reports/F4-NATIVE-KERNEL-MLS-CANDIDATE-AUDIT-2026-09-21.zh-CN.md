# F4 native weighted MLS 材料候选只读审计（2026-09-21）

本审计绑定既有 `f4-native-kernel-mls-v1` design/spec/result 与 RK4 trace summary JSON；没有打开或重算 H5，也没有提交 solver/GPU/长 H5 作业。

固定门槛保持为：每个 source 的 unknown ≤ `0.01`；CDF sup 差 ≤ `0.02`；完整事件窗；residence 必须结束或有可接受的非右删失证据。现有 trace 的 unknown 为 `0`，但没有 reference CDF comparison（因此 CDF gate 为 false）；`event_window_complete=false`、状态为 `right_censored_or_unresolved`，且 residence `right_censored_fraction=1.0`。故候选状态为 **blocked**，`credit=0`、`T2_macro=false`。

回执：`read_only=true`、`solver_started=false`、`gpu_started=false`、`long_h5_started=false`、registry/ledger mutation 均为 `0`；未重跑 ESS32 或 affine-bound。机器回执见同目录 `f4-native-kernel-mls-candidate-audit-v1-20260921.json`。
