# F3 `graph_raw` hidden16 seed17 full835 rollout 诊断

seed17 的既有 rollout 已自然完成 `835/835 transitions`、`836/836 frames`。本报告只收尾既有进程产生的 evaluation JSON、trajectory HDF5、validator 和训练绑定；没有重启或重复评测。

结论严格限定为完整的 diagnostic evidence：`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`qualification_credit=0`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`。诊断结果没有写入 registry、completion、ledger、denominator 或 gate。

## 冻结协议与绑定

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，canonical case `F3_DEV_00_a0p903125`，split `test`，登记分母 `835 transitions / 836 frames`。
- 模型：`graph_raw`、seed `17`、hidden `16`、updates `500`、参数量 `6,086`、centers/update `256`、learning rate `0.001`、Adam、normalization transitions `16`、`max_neighbors=192`。
- 训练证据：`500/500`、`evidence_status=complete`、`checkpoint_verified=true`、neighbor truncation=`0.0`；最终 loss MSE=`0.07728372514247894`，validation RMSE=`0.7626094110349643`。
- checkpoint SHA-256=`19cf88df48e369ce061a7dcd11b28d5e30864f30075deaa8d245ddc6184293ca`，bytes=`152145`。training receipt、实际 checkpoint、evaluation checkpoint path、model/hidden/seed/update/parameter metadata 均逐项 exact binding 通过。
- rollout 使用既有物理 GPU0 分配，进程内 device=`cuda:0`；本报告没有创建新的训练或评测进程。

## 完整性与 HDF5 validator

- evaluation：`status=completed`、`frames_executed=835`、`expected_frames=835`、`finite_rollout_complete=true`、`raw_error_coverage=835/835=1.0`。
- evaluation progress：最终 `status=completed`、elapsed=`11251.331096087117 s`、终点时间=`8.350012828223477 s`，`scientific_status=not_assessed`、failure=`null`。
- trajectory HDF5：position/velocity shape=`[836, 34560, 3]`，valid=`[836, 34560]`，time=`[836]`，mass=`[34560]`；position、velocity、mass 全 finite，mass positive/static，valid=`28892160/28892160` 全 true。
- HDF5 validator：`passed=true`、`complete=true`、`trajectory_frames=836`、`trajectory_transitions=835`、`executed_frame_count=836`、`tail_frame_count=0`、`production_artifacts_touched=false`、`qualification_credit=0`。validator 中的 `future_state_inputs` check 为 true 表示该断言通过；实际 evaluation/HDF5 属性均为 `future_state_inputs=false`。
- 总质量=`14.580000378191471 kg`；HDF5 attrs 明确 `autonomous_prediction=true`、`future_state_inputs=false`、`state_schema=core.state.native_velocity.v1`。

## 误差与物理审计

| horizon | position RMSE (m) | velocity RMSE (m/s) | position ADE (m) | velocity ADE (m/s) |
|---:|---:|---:|---:|---:|
| 1 | 0.00023158026137009321 | 0.0013297703906640834 | 0.0003424582581001611 | 0.0017556166154571663 |
| 10 | 0.0021386975604253794 | 0.006339813839870371 | 0.0030667119824534924 | 0.010190714830966114 |
| 50 | 0.011604879613374489 | 0.051947402727045934 | 0.0179227267060898 | 0.08367056074295147 |
| 100 | 0.03163042367023891 | 0.04601477748926135 | 0.049726332833618755 | 0.07070375764790764 |
| 200 | 0.11164386454563976 | 0.13326296781156166 | 0.17241766437435874 | 0.20553256293447716 |
| 400 | 0.8131583062289689 | 0.9313205611702353 | 1.2397777664127725 | 1.3645689915331014 |
| 600 | 15.131559929210397 | 19.20690302649759 | 18.47975045025494 | 23.045471323950913 |
| 700 | 60.18406919131819 | 97.3713850665137 | 72.32086773519794 | 114.30789045168866 |
| 800 | 270.55155914864633 | 539.275311845305 | 320.25904969902996 | 628.8191251514767 |
| 835 | 453.10199105793794 | 938.5552059785597 | 534.2122633163491 | 1093.8140975752535 |

selection score=`0.5774038900773645`，raw frame-mean position/velocity RMSE 分别为 `36.990732574509806 m` / `69.38583685341698 m/s`。step 835 的 position/velocity FDE 分别为 `534.2122633163491 m` / `1093.8140975752535 m/s`；长时域误差显著发散，因此不能把该 diagnostic 解释为合格模型。

physics receipt 中 `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`，最大 kinetic-energy error=`19261594.803977635 J`。wall-chord 结果为 `checked_static_saved_chords`（34921 particles、14.732297257141909 kg），仅是保存帧 chord 检查，不是连续路径或资格结论。

## 副作用与 receipts

本次仅新增本报告和对应 PLAN 文档；rollout 本身对源码、生产 HDF5、manifest、registry、completion、ledger、denominator、gate 均保持只读，diagnostic 不计入 formal training、T1、T2 或 credit。

机器可读报告：`F3-GRAPH-RAW-HIDDEN16-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json`。原始 evaluation、training receipt、checkpoint、trajectory、HDF5 validation 和 metric summary 的完整路径、bytes 与 SHA-256 均在该 JSON 中；其关键摘要如下：

- evaluation：`2ae71f675f07564682d34b687bedcf91178a15807428e05c930cce879d1675b9`
- evaluation progress：`c1777b5af9c369f7fc7e848de91e94dea1a97561d49b1b990e0cc7f4b319b226`
- trajectory HDF5：`20c82d33b989744f7d2b9acc5009f6908a51356d2f59c338b40e79c786603084`
- HDF5 validation：`19bf71e4bb113f482222f40bd0ea421be6743378f8156880e933d380fe219ba7`
- metric summary：`1f6768cd1edfb1d9967818ea4470d7f9027f05ec8adda88ef51b236679439fc1`
