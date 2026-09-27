# Core continuation status — 2026-09-27 — UPDATE-238

## F3 registered32 full temporal reader/oracle verification

在 `fe3383dd` 的 bounded chunk verifier 基础上，对真实 `core.dataset.v2` F3 manifest 执行了全量只读扫描；报告为 [`F3-FULL-TEMPORAL-VERIFY-2026-09-27.json`](F3-FULL-TEMPORAL-VERIFY-2026-09-27.json)。manifest SHA-256 为 `8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`，32/32 案例通过 source SHA、known-input contract、时间轴、full composite identity、valid/mass lifecycle、active finite state 和逐 transition privileged commit oracle。

覆盖结果：每例 836 帧、34,560 粒子、835 transitions；总计 **26,720 transitions**，train/validation/test 为 16/4/12，位置与原生速度最大绝对误差均为 `0.0`，总 wall `136.23439747397788 s`。扫描采用 8-frame bounded chunk，估计单例 numeric buffer `26,542,080` bytes、最多一个 HDF5 handle；没有经公共 `State` 逐帧复制，避免之前慢路径的无界耗时。

该结果只闭合 F3 reader 的真实全时域诊断层：`full_temporal_scan=true`、`qualification_inferred=false`，仍明确 `formal_training=false`、`T1_numerical=false`、`native_integrity_evaluated=false`、`gate_decision_eligible=false`、`qualification_credit=0`。它不证明 native producer/runtime 身份、求解器终止/flush、材料路径或数值资格，不修改 HDF5、split、registry、ledger、T1/T2 分母，也不替代资格研究和正式模型运行。

本轮只读生产 HDF5，未启动 solver/worker/GPU/queue。旧的 UPDATE-235 粗粒度报告保持不变；本次 receipt 是新增 artifact。
