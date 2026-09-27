# F3 MLP 500 更新 seed43 真实 50-step 诊断

本次独立只读诊断已完成：在物理 GPU0（`CUDA_VISIBLE_DEVICES=0`，进程内 `cuda:0`）使用真实案例 `F3_DEV_00_a0p903125` 完成 `500/500` training，并以 `maximum-steps=50 --diagnostic` 完成 `50/50` autonomous evaluate。该结果明确为 `diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`credit=0`（`qualification_credit=0`），不构成正式训练、资格或 gate 依据。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case=`F3_DEV_00_a0p903125`；split=`test`。
- 模型：`mlp`；seed=`43`；updates=`500`；centers/update=`256`；hidden=`8`；learning rate=`0.001`。
- normalization transitions=`16`；`max-neighbors=192`；evaluate chunk size=`34560`。
- 物理 GPU：`CUDA_VISIBLE_DEVICES=0`；进程内设备：`cuda:0`；run-id=`f3-mlp500-seed43-20260928`。
- 训练、评测、checkpoint、progress、output、log、trajectory 均使用唯一前缀 `/tmp/f3-mlp500-seed43-20260928-*`。

## 分母、自治与完整性

登记的完整案例分母保持为 **835 transitions / 836 frames**，没有因 bounded 评测缩小、改写或提交 mutation。此次只执行 50 个预测 transitions，trajectory 含初始帧共 51 帧；因此 `raw_error_coverage=50/835=0.059880239520958084`，`full_registered_denominator_complete=false` 是预期的右删失。`failure_category=maximum_steps_limit`、`first_failure_frame=51` 只表示达到用户指定的 50-step 上限，不是模型执行错误。

评测窗口 `requested_window_complete=true`、`finite_rollout_complete_for_requested_window=true`。trajectory 的 position 和 velocity 全部 finite；mass 全部 finite 且恒定；51 帧的 `valid` 全为 true（`valid_true_count=1,762,560`）。物理审计为 `mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`。`future_state_inputs=false` 同时由 evaluation receipt、progress 和 HDF5 属性确认。

## 训练与资源

训练 receipt 报告 `evidence_status=complete`、`checkpoint_verified=true`、`completed_updates=500`，参数量为 534；最后 progress 的 loss MSE 为 `0.3810088634490967`，邻居截断比例为 `0.0`。训练 wall=`981.641569016967 s`，receipt 精确 GPU allocator 峰值为 `191911936 B`（`183.021484375 MiB`），RSS 峰值为 `2869.984375 MiB`。

评测 progress 报告 `50/50`、耗时 `90.89424198796041 s`。GPU0 的 live `nvidia-smi` 最大观测为训练 `687 MiB`、评测 `607 MiB`，任务结束后为 `18 MiB`。评测期间 `ps` live RSS 样本最大为 `1,335,396 KiB`（`1304.09765625 MiB`）；这是观测最大值，不冒充 `core_learning.py` 未提供的进程峰值字段。

## position / velocity 指标

| 指标 | step 1 | step 10 | step 20 | step 30 | step 40 | step 50 |
|---|---:|---:|---:|---:|---:|---:|
| position RMSE (m) | 0.00018723056322705954 | 0.0015024665725263515 | 0.0034713839336615575 | 0.005596154691439162 | 0.0076319977007636075 | 0.010629219363048927 |
| velocity RMSE (m/s) | 0.0011425008731231535 | 0.004046152365670206 | 0.007019257654392019 | 0.009994738694410305 | 0.015973964744931894 | 0.026684503887126836 |

selection score=`0.9403820673463036`。raw frame-mean position/velocity RMSE 分别为 `0.004749995162400355 m` 与 `0.010350081415900696 m/s`；executed-frame scalar 分别为 `0.005624009469716738 m` 与 `0.012381800914621318 m/s`。50-step 末帧 ADE/FDE 分别为 position=`0.014258270119957867 m`、velocity=`0.04270907831770807 m/s`；executed-frame scalar ADE 分别为 `0.0066392215453490245 m` 与 `0.01646705122846382 m/s`。

## 只读边界与 artifact SHA-256

本次未修改源码、production HDF5、`PLAN.md`、manifest、registry、ledger、denominator 或 gate，未终止其他进程。仓库中只新增本报告及对应 JSON receipt。

machine receipt：[F3-MLP-500-SEED43-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-MLP-500-SEED43-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。

| artifact | bytes | SHA-256 |
|---|---:|---|
| training receipt `/tmp/...-training.json` | 10591 | `999a24cc0fbe0a8c10b8b49f5fa03604dbf936766c1d65a5a6373705584ac3e3` |
| checkpoint `/tmp/...-checkpoint.pt` | 48043 | `c2aab25a554c460dfccce9440298a27e7f1f31f4e4d43e5909761f0ede5a5dbb` |
| training progress `/tmp/...-training-progress.json` | 453 | `bf350202fdd289f199171cf2290d58f4293ee1c50cbdfd30252bde8b463832e6` |
| training log `/tmp/...-training.log` | 9269 | `c76dae341bbf1a1bff1d74d3c71f757eb536c13f97ae5dac4807931c762f180c` |
| evaluation receipt `/tmp/...-evaluation.json` | 513221 | `2e5f29225b2d1e8df63e8065ba51258bb47e1227b0eb028c5136674e0584f021` |
| evaluation progress `/tmp/...-evaluation-progress.json` | 633 | `e89da0d1e8f300686dadf26aec649622614d4914db0b0d4be85e8c9747c4e71c` |
| evaluation log `/tmp/...-evaluation.log` | 2079 | `4d49243984097751c7209f4424cf04750e62d63b890c70423a7e5cc8efb4f495` |
| trajectory `/tmp/...-trajectory.h5` | 44903680 | `4aa54f2eed65b0c484a1781ced0723597bb8011eda5d1551cb7234e066435221` |
| evaluation resource samples `/tmp/...-evaluation-resource-samples.log` | 52 | `59f89a0775229e3558d5c44fa870635acc208533ad49a0e3375dbb906b5c8a00` |

输入绑定：manifest 文件 SHA=`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`；case HDF5 SHA=`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`；`scripts/core_learning.py` SHA=`3eefe1441dabb350182090c3625f24a8209543a4a31d02521f283074c996c27b`。
