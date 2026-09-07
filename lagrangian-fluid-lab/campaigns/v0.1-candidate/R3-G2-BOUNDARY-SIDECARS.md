# R3 G2 有限边界三角形 sidecar 探索

状态：**candidate geometry only；几何已经可以供 wall-aware tracer 使用，但材料任务尚未接受。**

## 生成路径

`MkCells.vtk` 是 DualSPHysics GenCase 导出的 binary VTK POLYDATA。新的解析器只保留 `Type=0` 静止边界和 `Type=1` 规定运动边界，把每个有限多边形扇形三角化，并排除 `Type=3` 流体表面。对于 W06 旋转杯，`Type=1/Mk=17` 使用 HDF5 中当前帧的 `/control/cup_world_from_body` 变换；静止接收器和托盘逐帧重复。输出 sidecar 使用世界坐标，每个求解器导出帧都有完整的有限三角面集合，并以 gzip 压缩存储。

机器可读审计：`r3-g2-boundary-sidecars.json`；sidecar 目录：`sidecars/r3-g2-boundary/`。审计还会逐案例检查 release manifest 声明的相对路径、release 文件存在性，以及候选生成文件与 release 文件的 SHA-256 字节一致性。

## 当前覆盖

已为 W11 pilot 中全部 12 个 F1/F2/F3 流体案例生成 sidecar：

| 家族 | 案例数 | 三角面特点 |
|---|---:|---|
| F1 | 4 | 仅静止边界；障碍物和容器有限面均保留 |
| F2 | 5 | 40 个静止三角面 + 28 个运动杯体三角面，251 帧逐帧变换 |
| F3 | 3 | 仅静止边界；挡板有限面保留 |

12/12 sidecar 通过 frame count、世界坐标、有限值和非退化三角形审计。源文件中的流体 polygon 均被排除，避免把自由表面误判为墙。

## 仍然不能宣称什么

1. sidecar 只解决“插值时看见哪些有限壁面”的几何输入问题，不提供外部实验验证。
2. 12 个 F1/F2/F3 sidecar 已复制到 development release 并由 release manifest 链接；机器报告中的 `manifest_linkage.pass` 必须为真。但材料 destination regions 和 wall-aware transport contract 仍尚未冻结，F6 也没有 sidecar。
3. 需要用这些 sidecar 重跑示踪 convergence matrix，比较 wall-aware 与无壁面结果、支持半径、可靠率和质量加权目的地统计；之后才可决定是否把材料轨迹升级为 benchmark target。
4. 任何分辨率或几何定义变化都必须重新生成 sidecar，并通过源 VTK、frame axis 和 triangle hash 审计；不能复用旧 sidecar。
