# F7 直接扭矩观测 admission proposal（2026-09-22）

本 proposal 不是授权，不启动任何 GenCase、native solver、ComputeForces、GPU 或 queue。

它向 root review 请求一次且仅一次新的 CPU-only F7 torque anchor：

- 新 scope：`F7_pump_recirculation_direct_torque_anchor_x_v1`；
- 新 case/output namespace；
- 新 Definition、GenCase/native 产物和完整 `Part_XXXX.bi4` 帧；
- 对 `mk=2` 使用官方 `ComputeForces`，同时计算 intrinsic/extrinsic 轴向力矩；
- registry、ledger、matrix、T1/T2 分母和 qualification credit 全部保持 0；
- 不授权 15-row 矩阵、32-case production、GPU 或训练。

硬停止条件包括 native BI4 缺失或不连续、`mk=2`/粒子身份不一致、力矩字段缺失或非有限、轴语义未冻结、能量一致性失败，以及任何受保护 Core 状态变更。

当前状态仍是 `proposal_pending_root_review_not_authorized`。只有 root review 明确批准该单一 anchor 后，才能进入实际运行；现有 H5 canary 和角动量代理不会被当作直接扭矩证据。
