# Core 计划续接状态更新（2026-09-24，update 12）

本更新增加 F3 material row30 R003 的首个 RK stage 离线回放，不启动研究作业或改变资格分母。

- 对 trace 中 43 个最终 unknown seed，按绑定的执行实现、上一输出帧状态和 CFD source hash 回放其首个失败 interval。40 个 `wall_occluded` query 均越过封闭面 0.001655–0.347031 mm，而邻域 CFD 候选粒子仍在域内；另 3 个为 ESS 低于 4。详见 [R003 stage replay](F3-MATERIAL-ROW30-R003-STAGE-REPLAY-2026-09-24.zh-CN.md)。
- 证据指向 RK4 中间 stage 越界及独立的近壁 ESS 不足，不支持有限墙可见性误判。R003 unknown 门仍失败，独立 CDF 对照仍缺失；row30 仍未接受、T2 credit=0。
- 复核范围仅为已存在 trace 与 37 个对应 CFD native frames；未重跑完整轨迹或 worker，未启动 solver/GPU/queue，也未修改 registry、ledger、矩阵、阈值或旧证据。
- Core 总状态不变：`can_finalize=false`；T1 家族 F3/F4（2/3），宏观 T2（0/2），正式训练（0/9），目标 T1/material 分母仍缺 432/288。F3 row30 仍无 worker 启动许可；F4/F8 的既有授权边界不变。
