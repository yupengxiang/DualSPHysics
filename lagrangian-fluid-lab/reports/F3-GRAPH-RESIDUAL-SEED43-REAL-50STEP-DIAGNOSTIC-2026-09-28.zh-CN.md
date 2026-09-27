# F3 graph_residual seed43 真实数据 50-step 独立诊断

本次独立运行已完成，但结论严格限定为 bounded diagnostic-only：diagnostic_only=true、formal_eligible=false、qualification=false、credit=0、qualification_credit=0。它不构成正式训练、资格、gate 或 denominator 依据。

## 冻结协议

- manifest：campaigns/core-v1/f3-dataset-v2.json；data-root=.
- case：F3_DEV_00_a0p903125；split=test；model=graph_residual；seed=43。
- training：updates=500；centers/update=256；hidden=8；learning-rate=0.001。
- normalization transitions=16；max-neighbors=192；evaluation chunk=34560；maximum-steps=50。
- 物理 GPU：GPU2；CUDA_VISIBLE_DEVICES=2；进程内 device=cuda:0。
- 唯一临时产物前缀：/tmp/f3-graph-residual500-seed43-20260928-*。

## 训练验收

训练 receipt 报告 500/500、status=completed、evidence_status=complete，checkpoint update=500、schema=core.checkpoint.v1 且 checkpoint_verified=true。参数量为 1766，最后 loss MSE 为 0.31907951831817627，邻居截断比例最大值为 0.0。

normalization 来自 train split，requested/selected 为 16/16，采用 deterministic_evenly_spaced_train_transitions_v1。graph_residual residual prior 证据为 enabled，execution_calls=500、rows=17280000、finite=true、history_complete=true；dx_abs_max_m=0.009483016096055508，dv_abs_max_mps=0.108108289539814。

训练 wall=2217.797203957103 s；receipt-native GPU allocator 峰值为 1584764928 B（1511.349609375 MiB），receipt-native RSS 峰值为 3006.09765625 MiB。外部 GPU2 采样峰值为 7391 MiB，外部 ps RSS 采样峰值为 2720616 KiB（2656.8515625 MiB）。训练 launcher/Python 退出码为 0。

## 分母、窗口和因果输入

源 HDF5 的完整登记分母明确为 **835 transitions / 836 frames**。本次评测只执行用户指定的 50 transitions；trajectory 含初始帧共 51 帧。因此：

- requested window：50/50，requested_window_complete=true，finite_rollout_complete_for_requested_window=true；
- full registered denominator：full_registered_denominator_complete=false；
- raw error coverage：50/835=0.059880239520958084；
- failure_category=maximum_steps_limit、first_failure_frame=51 是 bounded 窗口的右删失，不是科学执行错误；
- scientific_status=not_assessed，没有把窗口结果解释成 full-horizon 结论；
- future_state_inputs=false，由 evaluation receipt、progress 和 trajectory HDF5 属性共同确认。

因此，50-step 窗口绝不能替代完整 835-transition/836-frame 分母，也不能被记作完整 rollout。

## trajectory、finite、mass 和 validity

trajectory HDF5 的 position/velocity shape 均为 [51, 34560, 3]，valid shape 为 [51, 34560]，time shape 为 [51]，mass shape 为 [34560]。position、velocity、mass、time 全部 finite；51 个状态帧的 valid mask 全为 true，valid_true_count=1762560。mass 最小/最大值都为 0.00042187501094304025 kg，time 从 0.0 s 到 0.5000171945830302 s。

已完成的 50 transitions 中，mass_error_abs_max_kg=0.0、changed_particle_mass_frames=0、validity_mismatch_frames=0；kinetic-energy error absolute maximum 为 0.025125850304006495 J。saved-chord wall diagnostic 为 421 particles、0.17760937960701995 kg，语义仅是已保存步 chord 检查，不是连续路径或 qualification gate。

## selection、position 和 velocity 指标

fixed-denominator selection score=0.9406098533927408。下表的 horizon 指标来自已执行的 finite prefix；frame mean 保留原始 frame-mean，executed-frame scalar 是执行窗口内的整体 scalar。

| step | position RMSE (m) | velocity RMSE (m/s) | position ADE (m) | velocity ADE (m/s) |
|---:|---:|---:|---:|---:|
| 1 | 0.00005605398225739141 | 0.005092877117404785 | 0.00009676327351077445 | 0.008630232385195995 |
| 10 | 0.0004370073616581921 | 0.013002803041554989 | 0.0005954376186723744 | 0.021920585683172202 |
| 20 | 0.0019707348070975425 | 0.028085847785592918 | 0.0031587875223002045 | 0.04724088434075968 |
| 30 | 0.0051571624563015025 | 0.04219208978899081 | 0.008455202878712098 | 0.07041909840266132 |
| 40 | 0.009522831888332011 | 0.049724258428188 | 0.015646003479305136 | 0.08115423328669809 |
| 50 | 0.01412328466913432 | 0.051256512746950575 | 0.022974642559765536 | 0.07960560302416193 |

raw frame-mean position/velocity RMSE 分别为 0.004901553935313918 m 与 0.032456000356391373 m/s；executed-frame scalar 分别为 0.006633422668641149 m 与 0.03622705633792571 m/s。step-50 position/velocity ADE/FDE 分别为 0.022974642559765536 m 与 0.07960560302416193 m/s。

## 资源、SHA 和只读边界

evaluation wall=1020.3887700000778 s；外部 GPU2 采样峰值为 3049 MiB，外部 ps RSS 采样峰值为 3404964 KiB（3325.16015625 MiB），evaluation launcher/Python 退出码为 0。任务结束后 GPU2 回到 18 MiB。外部 nvidia-smi/ps 数值是采样值，不冒充 CLI 未提供的 allocator/RSS 峰值。

| artifact | bytes | SHA-256 |
|---|---:|---|
| training receipt /tmp/f3-graph-residual500-seed43-20260928-training.json | 10847 | 8cb329d50b7647973c6a4ebfb1e7c924ab188219ce4f030b74331d0abff09fe4 |
| checkpoint /tmp/f3-graph-residual500-seed43-20260928-checkpoint.pt | 101549 | 947346691ff2695cfc5e3b347f0562ab3d53a73227c147c86df4f46050ef0baa |
| training progress | 488 | 4b38886edfb9e7a3ef38655b9d50b45ee6adacc8feb88ceddce5125d33f8e1c |
| training log | 9513 | 96a8155ffdbbeb902225c5a6b05db2de5d6a75952ee27bf4dcbac5c4df979770 |
| evaluation receipt /tmp/f3-graph-residual500-seed43-20260928-evaluation.json | 511373 | 360c522a4d43a1f0e99f5d1b548e3d67919b31e6e8ff9189359e45dd4f2387cc |
| evaluation progress | 645 | 7c6651626a37a22c12af6583d81ffedca02f11dce8ed85a1b9fe2138c0aeaba2 |
| evaluation log | 2101 | b0a91c15e6e15f5a2fcdaf0a6e5f754be54bfd3cc761aa8d64608d5bd13841ee |
| trajectory /tmp/f3-graph-residual500-seed43-20260928-trajectory.h5 | 44903680 | 5e657abc7cbd6e87d2369a31e736c8aa12f60ca0be720d1bed97f77da8c4143e |
| training resource samples | 149160 | c70d820690661e5e6d0767da30d8563169d6d54b8b79b64e2f4669d1a19a2c7a |
| evaluation resource samples | 64927 | 449842fcb0415e3bb44b55b8bde02b030bcc1d3feba4d07ff29dcf3242c1c6ce |

本次未修改源码、production HDF5、manifest、registry、ledger、denominator、gate 或 PLAN.md；未启动 solver/worker，未终止其他进程。仓库只新增本报告及对应 JSON；不追加 PLAN.md。

机器可读 receipt：[F3-GRAPH-RESIDUAL-SEED43-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/F3-GRAPH-RESIDUAL-SEED43-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。
