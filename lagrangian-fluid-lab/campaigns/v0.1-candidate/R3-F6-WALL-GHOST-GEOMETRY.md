# R3 F6 wall/ghost geometry audit

> 状态：**candidate-only / rejected；CPU-only，复用已生成 VTK 与审计 JSON，未运行 CFD 或 GPU。**

## 解释约定

`CfgInit_Normals.vtk` 与 `CfgInit_NormalsGhost.vtk` 的 `POINTS` 均是同一组边界点 `x_b`。本审计从 `FIELD/Normal` 读取初始位移 `n_b` 与求解器加倍后的 `n_g`，显式构造 `x_g=x_b+n_g` 和 `x_gamma=(x_b+x_g)/2`；不把 `BoundNor` 盲目归一化，也不把 ghost VTK 的 POINTS 误称为 ghost 坐标。

## 结果

| variant | zero normals | doubling residual | tank inward fraction | median x_gamma radius offset | overall gate |
|---|---:|---:|---:|---:|---|
| `baseline` | 792 ({'10': 792, '20': 0}) | 0 | 0.7939053728949479 | -0.044191 m | `candidate_geometry_only_rejected` |
| `inward_030` | 0 ({'10': 0, '20': 0}) | 0 | 0.8144199035288144 | -0.072876 m | `candidate_geometry_only_rejected` |
| `inward_020` | 0 ({'10': 0, '20': 0}) | 0 | 0.8093424727088093 | -0.062981 m | `candidate_geometry_only_rejected` |

## 判定

- canonical baseline 仍有 792 个 fixed/tank-side zero `BoundNor`，因此 normal completeness 失败。
- `-0.030 m` 与 `-0.020 m` 候选在现有二进制字段中均 zero-free，且 `n_g≈2n_b`；这只能证明序列化一致性，不能证明名义 tank 壁面或湿润几何正确。
- 两个 inward candidates 的 `x_gamma` 相对 2 m 名义半径发生系统偏移；当前 VTK 只提供边界点和位移字段，没有独立 ghost 坐标、压力力或 displaced-volume closure，故整体 gate 仍 rejected。
- 静水排水量仅复用既有 CPU diagnostic：`V_sub=0.00966257516 m³`、`m/rho=0.00975 m³`、相对误差 `-0.897%`；这不是本次几何 VTK 的物理验收。

## 下一步阻塞

1. Rebuild a nominal-geometry mDBC normal/ghost construction without unexplained zero vectors.
1. Independently validate x_gamma against the intended wall, corners and wetting surface; do not accept a radius offset solely from zero-normal removal.
1. Create a fixed-body force gauge and matched DBC/mDBC hydrostatic run after E0 passes.
1. Separate Chrono/body integration from the fixed hydrostatic closure.

机器可读结果：`r3-f6-wall-ghost-geometry.json`。本报告没有为 E1 固定浸没体矩阵解锁任何工况。
