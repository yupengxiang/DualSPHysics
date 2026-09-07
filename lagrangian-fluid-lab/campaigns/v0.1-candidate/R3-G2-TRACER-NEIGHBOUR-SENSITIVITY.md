# R3 G2 wall-aware 示踪邻居数/正则化/积分步敏感性

状态：**candidate-only；这轮只用于探路，不接受任何生产示踪配置为真值。**

## 运行范围

在 F1/F2/F3 各一个代表案例上，使用已审计的 world-space boundary sidecar，每个案例运行 6 个配置，共 18 个 CPU 设置。示踪点数为 16，保存帧 stride=1，支持距离上限为 1.75 dp。

默认设计为 one-factor-at-a-time：基线是 `neighbours=24`、`regularization=0.1 dp`、每个保存区间 4 个 Heun 子步；邻居数、正则化系数和子步数分别做扰动。报告中的每一项还记录了相对同案例基线的轨迹差异。

## 工程结果

- sidecar 时间轴对齐：True；有限且非退化：True。
- 扰动配置数：15；相对基线的最大轨迹 RMSE 差异为 1.968 dp。
- 具体案例、每个配置的末端可靠率、质量加权误差、支持距离、穿墙拒绝数和运行时间均在机器可读 JSON 中保存。

## 解释边界

1. 邻居数、正则化和积分子步会改变独立示踪器的数值轨迹；这种差异是配置敏感性证据，不是物理误差界或收敛证明。
2. sidecar 只提供候选有限三角面。开放面、障碍物/挡板隐式底部 cap 的语义仍需 policy；材料 destination region 也尚未定义。
3. 这轮只有三个代表案例和 16 个示踪点，不能代表家族覆盖，也不能据此选出全局生产默认值。
4. 当前比较仍是同一求解器导出与初始粒子身份轨迹的数值一致性检查，不是外部实验验证。

## 下一步

先补齐每个 boundary component 的 open/closed/rim/supporting policy 和 destination specification，再在更多分辨率、保存 cadence、示踪密度及已通过语义审计的案例上重复该矩阵；任何正式材料任务都应同时报告质量闭合、可靠率、支持距离、轨迹误差与目的地尾部统计。

机器可读证据：`r3-g2-tracer-neighbour-sensitivity.json`。
