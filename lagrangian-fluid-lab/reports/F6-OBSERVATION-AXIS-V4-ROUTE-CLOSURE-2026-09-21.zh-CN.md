# F6 观测轴 v4 路线闭包报告（2026-09-21）

## 结论

F6 观测轴 v4 当前路线已闭包，结论为“无新假设”。15-cell native preflight 全部通过；root-authorized 的 8-cell canary 审计为 7/8 scientific pass。cell-08 保留一个被排除流体粒子（`q=1, dp=0.015 m`），并保留 `excluded_particles_zero`、`native_identity_fixed`、`fluid_group_count_fixed` 三项硬门失败。

7 项 metadata-only 修复没有重新调用 solver，也没有改变 scientific fields；不存在 qualification credit。当前不授权剩余 7-cell 执行、cell-08 同输入重试、solver/GPU、queue、registry、ledger、matrix、T1 或 T2 变更。

## 可复核入口

- 路线卡：`campaigns/core-v1/cfd/f6-observation-axis-v4-third-t1-route-closed-v1.json`
- 决策回执：`campaigns/core-v1/evidence/f6-observation-axis-v4-third-t1-route-decision-receipt-v1.json`
- 闭包实现：`scripts/f6_observation_axis_v4_route_closed_v1.py`

执行 `python3 scripts/f6_observation_axis_v4_route_closed_v1.py --check` 可完成字段与 SHA-256 绑定核对；该检查为只读，不启动 solver、GenCase 或 GPU。
