# R3 geometry contracts synthetic diagnostics

状态：**candidate-only / rejected；CPU-only，未运行 CFD，未导入生产 tracer，未改变正式 schema。**

## 关键结论

- 动态三角形：逐顶点线性插值保持刚性的结论为 `False`，最大边长误差 `0.4142 m`；线性平移 + quaternion SLERP 保持刚性 `True`，误差 `0.0000 m`。
- 移动壁：端点和 midpoint 都未命中（`False`），但 swept-wall 在 `t=0.2100` 起检测到命中；midpoint-only 漏检为 `True`。
- G4：两个场景 AABB 完全相同而拓扑 fingerprint 不同，因此 AABB-only boundary summary non-identifiable = `True`。

## 有限支撑（观察量，不是 23/24 正式阈值）

| 支撑 | 样本数 | effective sample size | 几何 rank | 各向异性比 | 重构误差 [m/s] |
|---|---:|---:|---:|---:|---:|
| `isotropic_24` | 24 | 19.4233 | 3 | 0.4085 | 0.0314 |
| `isotropic_23` | 23 | 18.6187 | 3 | 0.4297 | 0.0326 |
| `one_sided_24` | 24 | 21.7515 | 3 | 0.0027 | 0.0829 |
| `planar_24` | 24 | 17.0652 | 2 | 0.5047 | 0.0447 |

对照：23-sample isotropic 与 24-sample one-sided 的质量不能按数量排序；正式 neighbour-count gate = `False`。

## 混合后 source label 反例

- 分离液团且无 barrier：geometry-only non-identifiable = `True`；同源 label oracle 仅作 candidate 反事实，不能成为永久过滤。
- 阻挡样本：有限 wall segment test 排除跨墙样本；source label filter applied = `False`。
- 开放样本：跨 source label 的开口样本保留 = `True`；永久按初始 source label 过滤会误删合法 transport。

## G4 当前几何输入契约

每个粒子—boundary component feature 明确包含 `distance_to_boundary_component_m`、`boundary_normal`、`boundary_type`、`wall_velocity_mps`；control 可含`prescribed_angular_velocity_radps`，不含未来 fluid/free-body state。
模型输入验证：plain=True，baffled=True；未来状态 negative control accepted? `False`。
统计完整报告失败数：candidate AABB representation failure=`1`，input-contract failure=`0`，总计 observed failure=`1`；contract assertions 为 `1` / `5`，failed ids = `aabb_only_summary_identifies_topology`。

## 边界

这些结果是 candidate-only 契约证据，不是物理验收，也没有修改生产 tracer、agent 或正式 schema。时空扫掠探针明确公开了采样 oracle；生产实现仍需提供保守 CCD/运动边界语义。

机器可读证据：`r3-geometry-contracts.json`；可重复入口：`diagnostics/r3_geometry_contracts/probe.py`。
