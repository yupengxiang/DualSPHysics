# R3 latest reviewer handoff

日期：2026-09-07  
分支：`codex/lagrangian-fluid-exploration`  
最新提交：`51bf8c4`

本轮严格按照云端审阅的 E0/E1 优先顺序执行。没有扩大六族机制矩阵，也没有重复小规模 G4 路线重跑。所有新文件都在 `lagrangian-fluid-lab/` 下；官方 DualSPHysics 路径未修改。

## 已完成的方向

### E0：F6 壁面/ghost 几何

提交 `51bf8c4`，报告为
[`R3-F6-WALL-GHOST-GEOMETRY.md`](R3-F6-WALL-GHOST-GEOMETRY.md)，机器结果为
[`r3-f6-wall-ghost-geometry.json`](r3-f6-wall-ghost-geometry.json)。审计直接读取已有二进制 `CfgInit_Normals.vtk` 和 `CfgInit_NormalsGhost.vtk` 的 `POINTS/FIELD`，没有重新运行 CFD。

- `POINTS` 在两个文件中相同，解释为边界点 `x_b`；`FIELD/Normal` 给出初始位移 `n_b` 与求解器加倍后的 `n_g`。
- 显式构造 `x_g=x_b+n_g`、`x_gamma=(x_b+x_g)/2`，并报告方向、模长、组件 (`Mk`)、水线分区和界面包围盒；没有把 `BoundNor` 盲目归一化。
- canonical mDBC 仍有 `792/24,335` 个固定壁零法向。
- `-0.030 m` 和 `-0.020 m` 候选的序列化法向为 zero-free，且 `n_g≈2n_b`；但是 `x_gamma` 相对名义 tank 半径出现系统偏移，VTK 没有独立 ghost 坐标、力或排水量闭合，因此整体 `candidate_geometry_only_rejected`。
- 既有外壳静水排量只作为诊断复用：`0.009662575 m³` 对 `0.00975 m³`，误差约 `-0.897%`；没有据此宣称 mDBC 物理正确。

### E1：固定浸没体静水力

提交 `03c675f`，目录为
[`cases/r3-f6-fixed-hydrostatic/`](cases/r3-f6-fixed-hydrostatic/)。结果是
`execution_status=blocked_preflight_no_run`、`acceptance_status=not_run_not_accepted`。

- E0 normal completeness 尚未通过；当前 mDBC baseline 仍有 792 个零法向。
- 现有 DBC/mDBC XML 走 `<floatings>` 路径，没有固定体定义或可审计固定体力 gauge；历史 mDBC 还触发 Chrono collision warning。
- 因此 nominal/deeper/shallower × DBC/mDBC 的 6 个主工况，以及至多 3 个 fine 工况，全部保持 `execute=false`，没有启动 GenCase、solver 或 GPU。
- 只检查了允许的 GPU 4--7；`gpu_indices_used=[]`，GPU 0--3 未查询/未使用。待固定体语义、名义壁面 ghost 几何和力测量路径成立后再解锁。

### 示踪与模型输入几何契约

提交 `c1f47e2`，目录为
[`diagnostics/r3_geometry_contracts/`](../../diagnostics/r3_geometry_contracts/)，新增 7 个 CPU-only 测试。

- 逐顶点线性插值会破坏刚体三角形；刚体 pose/quaternion SLERP 保持边长。
- 移动壁的端点和 midpoint 快照可同时漏检，而时空 swept-wall 检查可发现碰撞。
- 报告 effective sample size、支撑 rank/各向异性和插值重构误差；23/24 邻居差异不是正式阈值。
- 混合后不永久按 source label 过滤；分离液团、阻挡样本和开放样本均有反例。
- 相同 AABB 但不同挡板/开口拓扑被判为 non-identifiable；G4 输入包含边界组件距离、法向、类型、壁速度，允许 prescribed angular velocity，拒绝未来流体/自由体状态；失败数从全部检查统计而不是只平均成功案例。
- 该方向保持 `candidate_only_rejected`，没有修改生产 tracer 或正式 schema。

## 验证与资源

在 `lagrangian-fluid-lab/` 目录执行：

```text
PYTHONPATH=. .venv/bin/pytest -q
189 passed in 19.53s
```

本轮 E0/E1 和契约诊断均未使用 GPU。结束时 GPU 4--7 为空闲，GPU 0--3 保持既有外部负载；没有为了清零而中止或干扰外部任务。

## 当前冻结结论

可以继续保留开发版接口、身份/生命周期/lineage 语义、契约和审计工具；不能冻结 F6 的正式物理参考，也不能把 zero-normal 候选、固定浸没体矩阵或示踪几何 guard 标记为物理验收通过。下一阶段应先由审阅者确认：

1. 名义 tank 几何下可独立验证的 mDBC ghost/界面构造；
2. 不依赖 Chrono 的固定体 XML 与力测量 gauge；
3. 通过上述两个前置后，再执行 6+最多3 个有界静水力工况；
4. 之后才决定是否补 Chrono/body integration、F2/F1/F3 等其他家族。

## 可审阅入口

- [E0 几何报告](R3-F6-WALL-GHOST-GEOMETRY.md)
- [E0 机器报告](r3-f6-wall-ghost-geometry.json)
- [E1 no-run 报告](cases/r3-f6-fixed-hydrostatic/r3-f6-fixed-hydrostatic.md)
- [E1 机器报告](cases/r3-f6-fixed-hydrostatic/r3-f6-fixed-hydrostatic.json)
- [几何契约报告](../../diagnostics/r3_geometry_contracts/R3-GEOMETRY-CONTRACTS.md)
- [E0/E1 执行政策](R3-E0-E1-EXECUTION-POLICY.md)

