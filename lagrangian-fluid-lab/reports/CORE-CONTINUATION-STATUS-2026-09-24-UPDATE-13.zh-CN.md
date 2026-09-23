# Core 计划续接状态更新（2026-09-24，update 13）

本更新增加 F3 RK4 闭壁越界的 manufactured 回归用例，并刷新 F8 最新 scope 状态；不启动 solver 或资格矩阵。

- 新测试 [`test_rk4_censors_outward_intermediate_stage_at_closed_wall`](../tests/test_f3_native_volume_mls.py) 使用解析均匀外向流：初始 query 可可靠重建，k2/k4 越过闭壁后必须记为 unknown 并保持位置不推进。它锁定当前 fail-closed 行为，不修改生产积分器、阈值或 T2 资格。F3 R003 全部 stage 回放及外向法向速度证据见 [stage replay](F3-MATERIAL-ROW30-R003-STAGE-REPLAY-2026-09-24.zh-CN.md)。
- 验证：`pytest tests/test_f3_native_volume_mls.py`，6 passed。
- F8 最新候选是 R008，不是已关闭的 R002：R008 静态 scope review 已通过，CPU-native GenCase/native-decode preflight 与 postrun audit 通过但 credit=0；`solver_invocation_authorized=false`、`T1_numerical=false`，因此 F8 尚未成为第三个合格 T1 家族。
- 当前 `core_campaign.py status` 仍为 `can_finalize=false`：T1 家族 F3/F4（2/3），宏观 T2（0/2），正式训练（0/9），目标 T1/material 评测分母分别缺 432/288，独立复现未通过；因果 lineage 与 evidence validity 通过。没有启动 solver/GPU/queue/worker，也没有修改任何资格分母。
