# R4 W06 tracer bounded experiment

状态：**candidate-only / rejected；不构成正式材料目标或物理验收。**

本实验只复用 `W06_standard_slow_center` 已存在的 solver HDF5 和 release-linked finite-triangle sidecar，
运行 32/64 个质量加权 seeds 与 1/4 个显式 Heun 子步，记录 source×destination 质量、支持门失败和 swept-wall 拒绝。
没有启动 CFD、GenCase、CUDA 或 GPU。

## 输入与语义

- HDF5：`release/v0.1-development/data/W06_standard_slow_center.h5`，SHA-256 `52fe1b51f4998cab639058166612426f3b0e8a7b2b7217a131abfd8f14ac0b91`。
- sidecar：`release/v0.1-development/sidecars/r3-g2-boundary/W06_standard_slow_center.h5`，SHA-256 `f3cd6f5ea94c7cd8a3b03057c93de53efc24adf688336f62782a330296ca1fe0`。
- 帧数/时长：`251` / `2.500110 s`；保存 cadence 中位数 `0.010010000 s`。
- 初始流体：`1764` 粒子、`27.562500000 kg`。
- sidecar component labels：`triangle_mk`（explicit registry=False）。
- source label 只采用初始 `Mk`，不把它解释为混合后的材料身份。
- `inside_receiver` 是候选 AABB；`in_domain_unclassified`、`outside_domain` 和显式失败原因均单独保留。

## 结果

| seeds | substeps | final reliable mass | wall-crossing events | support-gate failures | max support (p95/dp) |
|---:|---:|---:|---:|---:|---:|
| 32 | 1 | 0.937642 | 0 | 6 | 1.1521043147079644 |
| 32 | 4 | 0.950680 | 1 | 43 | 1.1588076802197307 |
| 64 | 1 | 0.948980 | 1 | 138 | 1.0659376624207677 |
| 64 | 4 | 0.947279 | 1 | 197 | 1.0370457991308266 |

## Gate 结论

- 四个配置全部完成时，结果仍只说明同一实际案例中的 wall-aware tracer 数值行为；不说明目的地真值。
- sidecar 的有限三角面已实际参与每个子步，但 component 的 open-face/rim/supporting policy 尚未成为 release contract。
- 只有在 destination specification、source-destination closure、完整 failure reason provenance 和物理锚点均闭合后，才可讨论 material target；本轮不允许生成 20–30 例 tranche。

机器可读结果：`campaigns/v0.1-candidate/r4-w06-tracer-bounded-experiment.json`。
