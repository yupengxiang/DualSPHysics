# F3 graph_residual seed43 full835 长时域诊断

本报告记录一次只读、完整 autonomous diagnostic rollout。它不是 formal evidence、T1/T2 资格结果，也不授权任何生产或 gate 变更。

结论：执行链完整，`835/835 transitions`、`836/836 trajectory frames`、finite、mass 和 validity 检查均通过；但自由运行误差在长时域快速爆炸，因此该 checkpoint 作为长时域候选被拒绝。`formal_eligible=false`、`T1_numerical=false`、`T2_macro=false`、`qualification=false`、`qualification_credit=0`。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case `F3_DEV_00_a0p903125`；split `test`。
- 模型：`graph_residual`，seed `43`，hidden `8`，updates `500`，centers/update `256`，learning rate `0.001`，normalization transitions `16`，max-neighbors `192`。
- 评测参数：`maximum-steps=835`、`chunk-size=34560`、`--diagnostic`、autonomous、`future_state_inputs=false`。
- GPU：`CUDA_VISIBLE_DEVICES=6`，物理 GPU6（NVIDIA RTX 6000 Ada Generation），进程内 `cuda:0`。
- 已验证 checkpoint：`/tmp/f3-graph-residual500-seed43-20260928-checkpoint.pt`，SHA-256=`947346691ff2695cfc5e3b347f0562ab3d53a73227c147c86df4f46050ef0baa`，update=`500`；与既有 seed43 报告一致。
- 唯一 full835 临时前缀：`/tmp/f3-graph-residual500-seed43-full835-20260928-*`。

## 完整分母、因果输入和 validator

登记分母为 **835 transitions / 836 source frames**。本次完整执行结果为：

- evaluation receipt：`frames_executed=835`、`frames_expected=835`、`frames_predicted=835`、`execution_complete=true`、`finite_rollout_complete=true`；
- progress receipt：`status=completed`、`835/835`、`future_state_inputs=false`、`scientific_status=not_assessed`；
- raw error coverage：`1.0`；`failure_category=null`、`first_failure_frame=null`；
- trajectory：`836/836 frames`，因此完整分母为 `835/835 transitions`、`836/836 frames`；
- HDF5 validator：`passed=true`、`complete=true`、`trajectory_transitions=835`、`executed_frame_count=836`、`tail_frame_count=0`、`production_artifacts_touched=false`。

`future_state_inputs=false` 同时由 evaluation、progress 和 trajectory HDF5 属性确认；没有使用未来流体状态。

## finite、mass、validity 和轨迹完整性

- trajectory shape：position/velocity `[836, 34560, 3]`，valid `[836, 34560]`，time `[836]`，mass `[34560]`；
- position、velocity、time、mass 全部 finite；mass finite、positive、static，总质量 `14.580000378191471 kg`；
- `valid_all_true=true`，`valid_true_count=28,892,160`，`valid_false_count=0`；
- `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`；
- 时间从 `0.0 s` 到 `8.350012828223477 s`；trajectory HDF5 的 autonomous 属性为 true，`future_state_inputs=false`。

## selection 和长时域误差

selection score=`0.4920348186510375`。它是 registered selection penalty（越低越好），不是 qualification decision。

| horizon | position RMSE | velocity RMSE |
|---:|---:|---:|
| step 50 | `0.01412328466913432 m` | `0.051256512746950575 m/s` |
| step 835 | `780.2236162383314 m` | `1637.3650122957872 m/s` |

补充指标：position frame-mean RMSE=`37.258766193024144 m`，velocity frame-mean RMSE=`99.56572301212832 m/s`；step-835 position/velocity ADE 分别为 `202.3886322115033 m` 和 `366.07239335825943 m/s`。

physics receipt 的最大 kinetic-energy error 为 **`58632899.83787956 J`**；wall-chord 检查状态为 `checked_static_saved_chords`，该状态不等同于连续路径或资格 gate 通过。

因此，虽然状态保持 finite 且完整执行，长时域数值误差不可接受；50-step bounded 表现不能外推为 835-step 质量。

## 训练证据和运行资源

复用的 seed43 训练 receipt 显示 `500/500`、`evidence_status=complete`、`checkpoint_verified=true`，graph residual prior 为 `17280000` rows、`500` execution calls、finite 且 history complete；本次 full835 rollout 没有重新训练。

本次 evaluation wall=`8625.490081566153 s`。GPU6 显存充足，未发生 OOM；本报告不冒充未记录的 allocator peak。

## 资格状态和副作用边界

| 状态/副作用 | 结果 |
|---|---|
| `formal_eligible` | `false` |
| `T1_numerical` | `false` |
| `T2_macro` | `false` |
| `qualification` | `false` |
| `qualification_credit` | `0` |
| source code / production algorithm | 未修改 |
| production HDF5 | 未修改 |
| manifest / registry / ledger / denominator / gate | 未修改 |
| `PLAN.md` | 未修改 |
| solver / worker | 未启动 |

## Receipt SHA-256

- checkpoint：`947346691ff2695cfc5e3b347f0562ab3d53a73227c147c86df4f46050ef0baa`
- training receipt：`8cb329d50b7647973c6a4ebfb1e7c924ab188219ce4f030b74331d0abff09fe4`
- evaluation receipt：`699be1293d6c4502a971d6adb89cfcbf256464ca8c36a0a8e2ac43819a26d6d4`
- evaluation progress：`d35ee7dc3822ace72db6047bfaaeaac58c1ca5f3804a9c67479f71d953334f06`
- trajectory HDF5：`e71d3f484e5ec3f290ffbd7c9c562e483a0ce0a5bb497043be06a91a8d66cc4e`
- HDF5 validation：`03c0e72a08275c92d6ffac1cda0ab8276f1acba202bee49f81899d1a2588c649`
- evaluation log：`a65c7a5797d38610da2f410188125f1fb12d194b2e448bf19e4f2471e262e2e5`

机器可读报告：[F3-GRAPH-RESIDUAL-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-GRAPH-RESIDUAL-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json)。
