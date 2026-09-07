# R4 F1 core preflight

状态：**CPU GenCase-only structural evidence；不是 solver 运行、物理验收或生产准入。**

本报告严格覆盖 `plain_dam_break`、`center_obstacle`、`twin_obstacle_split_remerge` × `coarse/medium/fine` 九个独立工况。
每个工况均从现有 F1 定义复制到 R4 私有目录后单独改写；旧 R3 运行不计作本次执行。

## 固定控制

- `dp`：`{'coarse': 0.035, 'medium': 0.024, 'fine': 0.014}` m；`TimeMax=1.5` s；`TimeOut=0.001` s。
- `StepAlgorithm=1`，`VerletSteps=40`，`Boundary=1 (DBC)`。
- `SavePosDouble=2`，`Shifting=0`。
- 进程环境强制 `CUDA_VISIBLE_DEVICES=''`、`NVIDIA_VISIBLE_DEVICES='void'`；本脚本没有 solver 命令路径。

## 九个工况结果

| case | dp (m) | return code | total / bound / fluid | fluid mass (kg) | controls | anomalies |
|---|---:|---:|---:|---:|---|---|
| `R4_F1_plain_dam_break_coarse` | 0.035 | `0` | 3560 / 2160 / 1400 | 60.025000000000006 | yes | none observed |
| `R4_F1_plain_dam_break_medium` | 0.024 | `0` | 8468 / 4268 / 4200 | 58.0608 | yes | none observed |
| `R4_F1_plain_dam_break_fine` | 0.014 | `0` | 33202 / 11986 / 21216 | 58.216704 | yes | none observed |
| `R4_F1_center_obstacle_coarse` | 0.035 | `0` | 3680 / 2280 / 1400 | 60.025000000000006 | yes | none observed |
| `R4_F1_center_obstacle_medium` | 0.024 | `0` | 8720 / 4520 / 4200 | 58.0608 | yes | none observed |
| `R4_F1_center_obstacle_fine` | 0.014 | `0` | 33970 / 12754 / 21216 | 58.216704 | yes | none observed |
| `R4_F1_twin_obstacle_split_remerge_coarse` | 0.035 | `0` | 3776 / 2376 / 1400 | 60.025000000000006 | yes | none observed |
| `R4_F1_twin_obstacle_split_remerge_medium` | 0.024 | `0` | 8884 / 4684 / 4200 | 58.0608 | yes | none observed |
| `R4_F1_twin_obstacle_split_remerge_fine` | 0.014 | `0` | 34378 / 13162 / 21216 | 58.216704 | yes | none observed |

## 结构与质量记录

- GenCase 完成：`9/9`；结构异常工况：`0`。
- 每个工况记录了源定义、独立候选定义、GenCase 命令日志、`.xml/.bi4/.out` 与四类 VTK 产物的大小和 SHA-256。
- 几何审计检查了 VTK 点数、有限坐标、定义域外点、流体—边界重复位置和非正粒子数；质量审计检查了 `rhop0·dp³` 与 GenCase `massfluid` 的一致性，并报告跨分辨率质量 spread。
- 跨分辨率质量 spread 仅为诊断记录，不在本预检中设物理验收阈值。

## 边界声明

本产物的 `acceptance_status` 固定为 `preflight_structural_evidence_only`；未执行物理或参考验收，未提供 solver trajectory，也不作生产准入判断。下一步仍需在明确资源授权下运行同一协议的 solver，并完成 T1/T2 与外部观测门禁。

私有生成物：`campaigns/v0.1-candidate/artifacts/r4-f1-core-preflight/`；独立候选定义：`campaigns/v0.1-candidate/cases/r4-f1-core-preflight/`。
