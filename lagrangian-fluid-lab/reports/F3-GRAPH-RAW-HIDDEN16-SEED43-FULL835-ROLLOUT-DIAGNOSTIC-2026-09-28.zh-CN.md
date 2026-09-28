# F3 `graph_raw` hidden16 seed43 full835 rollout 诊断

seed43 的既有 rollout 已完成 `835/835 transitions`、`836/836 frames`。本报告只收尾既有进程产生的 evaluation JSON、trajectory HDF5、validator 和训练绑定；没有重启或重复评测。

结论严格限定为完整的 diagnostic evidence：`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`qualification_credit=0`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`。诊断结果没有写入 registry、completion、ledger、denominator 或 gate。

## 冻结协议与绑定

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，canonical case `F3_DEV_00_a0p903125`，split `test`，登记分母 `835 transitions / 836 frames`。
- 模型：`graph_raw`、seed `43`、hidden `16`、updates `500`、参数量 `6,086`、centers/update `256`、learning rate `0.001`、Adam、normalization transitions `16`、`max_neighbors=192`。
- 训练证据：`500/500`、`evidence_status=complete`、`checkpoint_verified=true`、neighbor truncation=`0.0`；最终 loss MSE=`0.17583727836608887`，validation RMSE=`0.7760517751218861`。
- checkpoint SHA-256=`c979614f7ae8e5d6e8924a9624d023c1633eb88a9fd28e5c04ad8d20ccddf2db`，bytes=`152081`。training receipt、实际 checkpoint、evaluation checkpoint path、model/hidden/seed/update/parameter metadata 均逐项 exact binding 通过。
- rollout 使用既有物理 GPU6 分配，进程内 device=`cuda:0`；本报告没有创建新的训练或评测进程。

## 完整性与 HDF5 validator

- evaluation：`status=completed`、`frames_executed=835`、`expected_frames=835`、`finite_rollout_complete=true`、`raw_error_coverage=835/835=1.0`。
- evaluation progress：最终 `status=completed`、elapsed=`8709.411436522845 s`、终点时间=`8.350012828223477 s`，`scientific_status=not_assessed`、failure=`null`。
- trajectory HDF5：position/velocity shape=`[836, 34560, 3]`，valid=`[836, 34560]`，time=`[836]`，mass=`[34560]`；position、velocity、mass 全 finite，mass positive/static，valid=`28,892,160/28,892,160` 全 true。
- HDF5 validator：`passed=true`、`complete=true`、`trajectory_frames=836`、`trajectory_transitions=835`、`executed_frame_count=836`、`tail_frame_count=0`、`production_artifacts_touched=false`、`qualification_credit=0`。validator 中的 `future_state_inputs` check 为 true 表示该断言通过；实际 evaluation/HDF5 属性均为 `future_state_inputs=false`。
- 总质量=`14.580000378191471 kg`；HDF5 attrs 明确 `autonomous_prediction=true`、`future_state_inputs=false`、`state_schema=core.state.native_velocity.v1`。

## 误差与物理审计

| horizon | position RMSE (m) | velocity RMSE (m/s) | position ADE (m) | velocity ADE (m/s) |
|---:|---:|---:|---:|---:|
| 1 | 0.00023333244658730657 | 0.0012311018575968155 | 0.00035007852904894975 | 0.0013516159086552084 |
| 10 | 0.0014594985986128494 | 0.005301222783873578 | 0.002269787280172171 | 0.00833376903742649 |
| 50 | 0.008437241827359814 | 0.026409864126179586 | 0.012457019308252118 | 0.04247680933626576 |
| 100 | 0.028189892801693723 | 0.08150123428742939 | 0.04221531761043094 | 0.13532062615589763 |
| 200 | 0.1572181191692692 | 0.1567059621360179 | 0.2414652817517718 | 0.2600789044226032 |
| 400 | 1.3338188701454559 | 2.0372378042328814 | 2.0740368905820987 | 3.153575702800109 |
| 600 | 11.695164386281242 | 16.825563827773127 | 17.410739238100852 | 25.785803861163515 |
| 700 | 32.07397491800031 | 44.35673699949688 | 48.29133622708807 | 68.79203040800068 |
| 800 | 77.28428051212383 | 110.71007764744024 | 120.3503392273663 | 176.55623433373978 |
| 835 | 108.22196128989448 | 160.14339697973475 | 170.14860090134513 | 253.19753919651902 |

selection score=`0.6210860481860428`，raw frame-mean position/velocity RMSE 分别为 `13.789128223465472 m` / `19.614892178259495 m/s`。step 835 的 position/velocity FDE 分别为 `170.14860090134513 m` / `253.19753919651902 m/s`；长时域误差显著发散，因此不能把该 diagnostic 解释为合格模型。

physics receipt 中 `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`，但最大 kinetic-energy error=`560901.7010638689 J`。wall-chord 结果为 `checked_static_saved_chords`（22417 particles、9.457172120310133 kg），仅是保存帧 chord 检查，不是连续路径或资格结论。

## 副作用与 receipts

本次仅新增本报告和对应 PLAN 文档；rollout 本身对源码、生产 HDF5、manifest、registry、completion、ledger、denominator、gate 均保持只读，diagnostic 不计入 formal training、T1、T2 或 credit。

机器可读报告：[F3-GRAPH-RAW-HIDDEN16-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-HIDDEN16-SEED43-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json)。原始 evaluation、training receipt、checkpoint、trajectory、HDF5 validation 和 metric summary 的完整路径、bytes 与 SHA-256 均在该 JSON 中；其关键摘要如下：

- evaluation：`351c57876a60a2d2a172e4c0b4abd7bc2fe5ca9427a6951abb18dc3c1b8d68c`
- evaluation progress：`bfa4b14567015cf76afc7763fa40398f10599dd7c4d292b9ff8fb081078164ca`
- trajectory HDF5：`d796d58dc55ae1b19521dd0059614d2d4ca3d4922184332ece2f7730bc35232b`
- HDF5 validation：`3db854007f267573b2af54045b7551b616bc67f435ec0fbb06cc605e2e6c12a9`
- metric summary：`a2200041797c4fb4b605844a3c3696e317da2882283e5e2a20d824e6b70e89e0`
