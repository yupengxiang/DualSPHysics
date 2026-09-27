# F3 MLP seed29 全 835-step autonomous rollout 诊断

本次独立只读诊断已完成：使用已验证 checkpoint `/tmp/f3-mlp500-seed29-20260928-checkpoint.pt`，在 GPU4（`CUDA_VISIBLE_DEVICES=4`，进程内 `cuda:0`）对 `F3_DEV_00_a0p903125` 的 test split 完成完整 `835/835` transitions、`836/836` trajectory frames。没有重新训练，也没有覆盖既有 50-step 产物。

结论：执行分母、finite 状态、HDF5 结构和质量/validity 闭合均通过；但 step 835 的误差高于 step 50，结果仍明确是 non-formal diagnostic，不是资格结果。`formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、`qualification_credit=0`。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case=`F3_DEV_00_a0p903125`；split=`test`。
- 模型：`mlp`；seed=`29`；updates=`500`；centers/update=`256`；hidden=`8`；learning rate=`0.001`；optimizer=`Adam`；trainable parameter count=`534`。
- normalization transitions=`16`，source split=`train`，target=`raw_dual_increment_train_shared`，max-neighbors=`192`。
- 评测：`maximum-steps=835`、`chunk-size=34560`、`--device cuda:0`、`--diagnostic`、autonomous。
- 运行时：`CUDA_VISIBLE_DEVICES=4`，物理 GPU4，进程内设备 `cuda:0`；没有触碰 GPU1/GPU3 的既有外部任务，也没有终止任何进程。
- checkpoint 已核对存在；SHA-256=`61b3384f0b9294593136437a331607e4347b084e0f9cf3324620c15da3d92b03`，大小 `47659` bytes，与既有 seed29 训练报告一致。

## 完整分母、自治与 finite/物理闭合

- 固定登记分母保持为 **835 transitions / 836 source frames**；本次实际完成 `835/835`，trajectory 保存 `836/836` frames，`tail_frame_count=0`，raw error coverage=`1.0`。
- evaluation receipt：`requested_window_complete=true`、`finite_rollout_complete_for_requested_window=true`、`failure_category=null`、`first_failure_frame=null`。
- `future_state_inputs=false`：由 evaluation receipt、progress receipt 和 HDF5 属性共同确认；预测过程为 autonomous rollout。
- position、velocity、mass、time 全部 finite；position/velocity shape 为 `[836,34560,3]`，valid shape 为 `[836,34560]`。
- valid 全部为 true：`valid_true_count=28,892,160`、`valid_false_count=0`；mass finite、positive、static，总质量=`14.580000378191471 kg`。
- 物理侧车：`mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`；最大 absolute kinetic-energy error=`0.7315161477683964 J`。
- HDF5 validator receipt：`passed=true`、`complete=true`、`trajectory_frames=836`、`trajectory_transitions=835`、`executed_frame_count=836`、`tail_frame_count=0`。

## 关键指标

`selection_score=0.09284432062180459`。该分数对应完整登记分母，语义是 registered selection penalty（越低越好），不是 qualification decision。

| horizon | position RMSE (m) | velocity RMSE (m/s) |
|---:|---:|---:|
| step 50 | 0.005127741279630813 | 0.03627122499267607 |
| step 835 | 0.31004393675611147 | 0.20390414990592887 |

全执行帧 scalar 指标为 position RMSE=`0.15630489336672176 m`、velocity RMSE=`0.1402731542942554 m/s`；position ADE/FDE=`0.20982420810864258 / 0.5119484314884986 m`，velocity ADE/FDE=`0.1892239547134749 / 0.3230350272959475 m/s`。step 835 相对于 step 50 的误差增长说明不能把 bounded 结果外推为长时域质量保证。

## Qualification 状态与只读边界

- `diagnostic_only=true`、`non_formal_diagnostic=true`。
- `formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、`qualification_credit=0`。
- 未修改源码、production HDF5、manifest、registry、ledger、denominator、gate 或 `PLAN.md`；未启动 solver/worker，未重新训练，未覆盖已有 50-step 产物。
- HDF5 validator 和本报告均标记 `production_artifacts_touched=false`；仓库只新增本任务指定的 JSON 与中文 Markdown 两个报告文件。

## Receipt 与 SHA-256

| artifact | bytes | SHA-256 |
|---|---:|---|
| checkpoint `/tmp/f3-mlp500-seed29-20260928-checkpoint.pt` | 47659 | `61b3384f0b9294593136437a331607e4347b084e0f9cf3324620c15da3d92b03` |
| training receipt `/tmp/f3-mlp500-seed29-20260928-training.json` | 9947 | `659752904c79533b5d25c1fd4d0b6d7cdb49cd78cd0bf37bdca5a78540f4e378` |
| evaluation receipt `/tmp/f3-mlp500-seed29-full835-20260928-evaluation.json` | 6424889 | `a759bd84aedb65462e259af0ebce819a488acb429be144ce405f5f1e05ac88cf` |
| evaluation progress `/tmp/f3-mlp500-seed29-full835-20260928-evaluation-progress.json` | 645 | `3083dc9a02530da4c33bb7ad5173c5d765ebacc7a8b94c7a3120f9d0aff52c57` |
| trajectory `/tmp/f3-mlp500-seed29-full835-20260928-trajectory.h5` | 723148320 | `1c79a3c5e4c66f909f514e6d85aca49444089d10dbc7cd034041c357f8d5c282` |
| HDF5 validation `/tmp/f3-mlp500-seed29-full835-20260928-hdf5-validation.json` | 1407 | `31ed4a2e6a94649493162725ca8f18a138165c43b4727d6181b78314226ddebb` |
| run log `/tmp/f3-mlp500-seed29-full835-20260928-run.log` | 2083 | `0e226243bc19418770e7f10cbda6602a73fd024605ebea2a2df139c900a64cb4` |

输入绑定：manifest SHA-256=`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；case HDF5 SHA-256=`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`；`scripts/core_learning.py` SHA-256=`3eefe1441dabb350182090c3625f24a8209543a4a31d02521f283074c996c27b`。

机器可读报告：[F3-MLP-SEED29-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json](F3-MLP-SEED29-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json)。
