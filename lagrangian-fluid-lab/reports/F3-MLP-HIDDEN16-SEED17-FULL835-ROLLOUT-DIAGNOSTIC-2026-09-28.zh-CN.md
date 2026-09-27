# F3 MLP hidden16/seed17 全 835-step rollout diagnostic

本次只读长时域诊断已完成：使用既有、已核验的 hidden16/seed17 checkpoint，在 GPU6（`CUDA_VISIBLE_DEVICES=6`，进程内 `cuda:0`）对真实案例 `F3_DEV_00_a0p903125` 的 test split 完成完整 `835/835 transitions` 与 `836/836 trajectory frames`。没有重新训练，也没有覆盖既有 bounded 产物。

结论：执行分母、finite 状态、HDF5 结构以及 mass/validity 闭合均通过；但长时域误差从 step 50 到 step 835 显著放大，因此本结果明确是 `diagnostic-only`，不是正式资格结果。`formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、`qualification_credit=0`。

## 冻结协议与 checkpoint

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case=`F3_DEV_00_a0p903125`；split=`test`。
- 模型：`mlp`；seed=`17`；训练 checkpoint update=`500`；hidden=`16`；centers/update=`256`；learning rate=`0.001`；trainable parameter count=`1574`。
- normalization transitions=`16`；`max-neighbors=192`；评测 `chunk-size=34560`、`maximum-steps=835`、`--diagnostic`、autonomous、`future_state_inputs=false`。
- checkpoint：`/tmp/f3-mlp500-hidden16-seed17-20260928-checkpoint.pt`，SHA-256=`8cd8304c2b8ebda145ec99b1faf1623a0fb222d582eaaabfa7cf00600fb9ceac`，大小 `60332` bytes；与既有 hidden16 bounded 报告中的 checkpoint SHA 完全一致。
- manifest SHA-256=`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；case HDF5 SHA-256=`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`；`scripts/core_learning.py` SHA-256=`3eefe1441dabb350182090c3625f24a8209543a4a31d02521f283074c996c27b`。

## 完整分母、自治和 HDF5 完整性

- 固定登记分母保持为 **835 transitions / 836 trajectory frames**；本次实际完成 `835/835` transitions，保存 `836/836` frames，raw error coverage=`1.0`。
- evaluation progress：`status=completed`、`frames_executed=835`、`expected_frames=835`、`finite_rollout_complete=true`、`future_state_inputs=false`、`scientific_failure_category=null`。
- evaluation receipt：`failure_category=null`、`first_failure_frame=null`、`execution_complete=true`、`finite_rollout_complete=true`。
- HDF5 validator：`passed=true`、`complete=true`、`fail_closed=false`、`trajectory_frames=836`、`trajectory_transitions=835`、`executed_frame_count=836`、`tail_frame_count=0`。
- trajectory shape：position/velocity `[836, 34560, 3]`，valid `[836, 34560]`；position 和 velocity 全部 finite（各 `86676480` 个 finite 分量）。
- valid 全部为 true：`valid_true_count=28892160`、`valid_false_count=0`；mass finite、positive、static，总质量=`14.580000378191471 kg`。
- evaluation 与 HDF5 属性均确认 `future_state_inputs=false`；预测过程是 autonomous rollout，reference state 只用于 rollout 后评分与诊断。

## 关键长时域指标

selection score=`0.36276549209301584`。该分数是完整登记分母上的 registered selection penalty（越低越好），不是 qualification decision。raw frame mean 是 835 个执行 transition 的逐帧 RMSE 平均值。

| horizon | position RMSE (m) | velocity RMSE (m/s) |
|---:|---:|---:|
| step 50 | 0.01027835577014365 | 0.0593277591759465 |
| step 835 | 14.38490966715898 | 1.746069502248655 |
| raw frame mean | 2.5760087669360936 | 0.3372982978738331 |

额外 scalar 指标：position RMSE/ADE/FDE=`4.376734320540036 / 4.048957457625704 / 22.756258097156625 m`；velocity RMSE/ADE/FDE=`0.4840404463116826 / 0.4936361397416853 / 2.542995226015867 m/s`。step 835 相对 step 50 的误差增长说明 bounded 结果不能外推为长时域质量保证。

## Physics、资格状态与只读边界

- `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`。
- 最大 absolute kinetic-energy error=`60.41556468773562 J`；wall-chord diagnostic status=`checked_static_saved_chords`。
- `diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、`qualification_credit=0`。
- 未修改源码、生产 HDF5、manifest、registry、ledger、denominator、gate 或 `PLAN.md`；未启动 solver/worker/queue，未终止其他进程，也未覆盖已有 bounded 产物。
- 本任务只应提交本报告对应的 JSON 与中文 Markdown 两个文件；训练、评测、trajectory 与 HDF5 validator receipts 保留在 `/tmp/f3-mlp500-hidden16-seed17-*` 和 `/tmp/f3-mlp500-hidden16-seed17-full835-*`。

## Receipt SHA-256

| artifact | bytes | SHA-256 |
|---|---:|---|
| checkpoint | 60332 | `8cd8304c2b8ebda145ec99b1faf1623a0fb222d582eaaabfa7cf00600fb9ceac` |
| training receipt | 9985 | `be78c0286d8d6a681bb6323c6887f3351710947e13aab8b98ae3b4aadaffd245` |
| evaluation receipt | 6405479 | `06956dfec001c23bc23be5efdc74a29e079281d5d362cdab567f0dec51066c9c` |
| evaluation progress | 654 | `fac07099de9d9d506ec78b318eedc79bacecf1d442579fde18fa71ebe2329874` |
| trajectory | 723148320 | `c9faa0578ba89cad982fd57f3fbafce03ec0285b14dd6a221e21c315dd4f8891` |
| HDF5 validation | 1425 | `e08846218cc6a3f01bae4044aa45e9e64a0d72f0fac515d0c5168b194b21bc7e` |
| evaluation log | 2092 | `d7eb7b525cb6d066210fde5a6aa616f6870e66d28ea0231b0ef0652a0dd552a5` |

机器可读报告：[F3-MLP-HIDDEN16-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json](F3-MLP-HIDDEN16-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json)。
