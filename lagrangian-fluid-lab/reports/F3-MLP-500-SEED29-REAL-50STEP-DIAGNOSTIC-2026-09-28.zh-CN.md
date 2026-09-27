# F3 MLP 500 更新 seed29 真实 50-step 诊断

本次独立只读诊断已完成：使用真实案例 `F3_DEV_00_a0p903125` 完成 `500/500` training，并以 `maximum-steps=50 --diagnostic` 完成 `50/50` autonomous evaluate。该结果明确为 `diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`credit=0`（`qualification_credit=0`），不构成正式训练、资格或 gate 依据。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case=`F3_DEV_00_a0p903125`；split=`test`。
- 模型：`mlp`；seed=`29`；updates=`500`；centers/update=`256`；hidden=`8`；learning rate=`0.001`；optimizer=`Adam`。
- history states=`1`；normalization source split=`train`；target normalization=`raw_dual_increment_train_shared`；normalization transitions=`16`；selection policy=`deterministic_evenly_spaced_train_transitions_v1`。
- `max-neighbors=192`；evaluate chunk size=`34560`；进程设备=`cuda:0`；运行时未在提供的 receipt/log 中记录 `CUDA_VISIBLE_DEVICES` 或物理 GPU 编号。
- run-id=`f3-mlp500-seed29-20260928`；训练关闭 validation cadence（`validation-every=0`）和 milestone evaluation；训练、评测、checkpoint、progress、output、log、trajectory 均使用唯一前缀 `/tmp/f3-mlp500-seed29-20260928-*`。

## 分母、自治与完整性

登记的完整案例分母保持为 **835 transitions / 836 frames**，没有因 bounded 评测缩小、改写或提交 mutation。此次只执行 50 个预测 transitions，trajectory 含初始帧共 51 帧；因此 `raw_error_coverage=50/835=0.059880239520958084`，`full_registered_denominator_complete=false` 是预期的右删失。`failure_category=maximum_steps_limit`、`first_failure_frame=51` 只表示达到用户指定的 50-step 上限，不是模型执行错误。

评测窗口 `requested_window_complete=true`、`finite_rollout_complete_for_requested_window=true`。trajectory 的 position、velocity、mass、time 全部 finite；51 帧的 `valid` 全为 true（`valid_true_count=1,762,560`），mass 恒定为 `0.00042187501094304025 kg`。HDF5 shape 为 position/velocity=`[51,34560,3]`、valid=`[51,34560]`、time=`[51]`、mass/particle_id/particle_zone=`[34560]`，`future_state_inputs=false` 同时由 evaluation receipt、progress 和 HDF5 属性确认。

物理审计为 `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`；kinetic-energy error absolute max=`0.03850225509297513 J`。保存步 wall-chord 检查为 `checked_static_saved_chords`，其结果只是诊断，不构成连续路径物理有效性结论。

## 训练与资源

训练 receipt 报告 `evidence_status=complete`、`checkpoint_verified=true`、`completed_updates=500`，参数量为 `534`；最后 progress 的 loss MSE 为 `0.3293156027793884`，邻居截断比例为 `0.0`。训练 wall=`979.0291839798447 s`，receipt 精确 GPU allocator 峰值为 `133975040 B`（`127.7685546875 MiB`），RSS 峰值为 `2557.7734375 MiB`。

评测 progress 报告 `50/50`、`execution_complete=true`、`finite_rollout_complete=true`，耗时 `92.31227771192789 s`。提供的前缀下没有独立 evaluation resource-samples 文件，评测 receipt 也不输出进程峰值 RSS；因此不补写未被证据记录的评测资源峰值。

## position / velocity 指标

| 指标 | step 1 | step 10 | step 20 | step 30 | step 40 | step 50 |
|---|---:|---:|---:|---:|---:|---:|
| position RMSE (m) | 0.00016903892955853173 | 0.0015007259541054195 | 0.003513011243871432 | 0.005513869800260456 | 0.005943197227050748 | 0.005127741279630813 |
| velocity RMSE (m/s) | 0.0012356190321687552 | 0.0024936276836558208 | 0.004043541436354245 | 0.008620003175118733 | 0.020258409980903568 | 0.03627122499267607 |

selection score=`0.9403588386806812`，对应固定完整登记分母，不能解释为 50-step 窗口的完整案例分数。50-step 执行帧平均 position/velocity RMSE 分别为 `0.0038564723759578457 m` 和 `0.010994765233132945 m/s`；executed-frame scalar 分别为 `0.00432811639432608 m` 和 `0.015081778772422139 m/s`。50-step 末帧 ADE/FDE 分别为 position=`0.007520640089215316 m`、velocity=`0.05506702513997362 m/s`；executed-frame scalar ADE 分别为 `0.005658825004949581 m` 和 `0.016704888684912118 m/s`。

## 只读边界与 receipt

本次未修改源码、production HDF5、`PLAN.md`、manifest、registry、ledger、denominator 或 gate，未终止其他进程；只新增本报告及对应 JSON receipt。机器可读 receipt：[F3-MLP-500-SEED29-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-MLP-500-SEED29-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。

## SHA-256

| artifact | bytes | SHA-256 |
|---|---:|---|
| training receipt `/tmp/...-training.json` | 9947 | `659752904c79533b5d25c1fd4d0b6d7cdb49cd78cd0bf37bdca5a78540f4e378` |
| checkpoint `/tmp/...-checkpoint.pt` | 47659 | `61b3384f0b9294593136437a331607e4347b084e0f9cf3324620c15da3d92b03` |
| training progress `/tmp/...-training-progress.json` | 453 | `08ba0d64bdc1e5e799b91fb030a1068fa106ad43137475a5c911f013975f3` |
| training log `/tmp/...-train.log` | 8623 | `30bd42e9ad7e884b027b1a40a3d89952bf6462229bbd86745cf4be7d886a656b` |
| evaluation receipt `/tmp/...-evaluation.json` | 513436 | `b38a0b75e770ac8dc7553fadcbcf8d7b134ff17875f71fb53822d66af1a78667` |
| evaluation progress `/tmp/...-evaluation-progress.json` | 633 | `2886b57fbcaffce8083d762bac931f9aef1bd00948700c9ee8f8218e000c4c41` |
| evaluation log `/tmp/...-evaluate.log` | 2079 | `b6eb3234ae78c1aa3b10092fcb730b29df6ba0df27ca8369513f492daa94e548` |
| trajectory `/tmp/...-trajectory.h5` | 44903680 | `5712cd4c8b294e701f62bd831a09f50ed949664956ebbb35bb1e361b2014b209` |

输入绑定：manifest 文件 SHA=`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；case HDF5 SHA=`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`；`scripts/core_learning.py` SHA=`3eefe1441dabb350182090c3625f24a8209543a4a31d02521f283074c996c27b`。
