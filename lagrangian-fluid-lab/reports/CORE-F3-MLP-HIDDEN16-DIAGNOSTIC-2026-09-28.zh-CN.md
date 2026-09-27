# CORE F3 MLP hidden=16 独立诊断 — 2026-09-28

本次独立只读诊断已完成：在 GPU5（`CUDA_VISIBLE_DEVICES=5`，进程内 `cuda:0`）上用真实注册 F3 数据完成 `mlp`、seed=17、500 updates 训练，并用同一 checkpoint 对代表性 test case `F3_DEV_00_a0p903125` 完成 50-step autonomous diagnostic evaluation。该证据链是 bounded diagnostic only：manifest 当前 `formal_release=false`，不产生 formal eligibility、T1/T2 qualification 或 credit，也不改变任何 gate/分母。

## 冻结协议与完成状态

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case split=`test`。
- 模型：`mlp`，seed `17`，updates `500`，centers/update `256`，hidden `16`，learning rate `0.001`。
- train normalization transitions `16`；`max-neighbors=192`；history states=`1`；target normalization=`raw_dual_increment_train_shared`。
- 训练额外关闭 validation cadence（`validation-every=0`）与 milestone evaluation；训练/归一化只使用 train split。
- 训练：`500/500`，`evidence_status=complete`，checkpoint update=`500`，`checkpoint_verified=true`；parameter count=`1574`；wall=`979.106672747992 s`；最后记录 loss MSE=`0.0813000351190567`；记录的邻居截断比例均为 `0.0`。
- 评估：`maximum-steps=50`，`50/50` 帧执行且 finite；progress `status=completed`，elapsed=`98.55567635595798 s`。

## Coverage、因果输入与 mass/validity

固定完整分母仍是 `835` transitions（`836` frames）。本次只执行 50 帧，因此 receipt 保留 `failure_category=maximum_steps_limit`、`first_failure_frame=51`，这表示 bounded 窗口的正常右删失，不是模型执行失败；raw error coverage=`50/835=0.059880239520958084`。完整登记分母没有被缩小或重定义。

`future_state_inputs=false` 同时出现在 evaluation、rollout progress、trajectory 属性和 receipt。模型每一步只反馈自己的上一预测状态；reference state 仅在预测后用于评分/物理诊断，未作为 predictor 输入。

trajectory 为 `51 × 34560`（含初始帧），position/velocity 全部 finite，`valid` 全部为 true（`1,762,560/1,762,560`），复合 identity 唯一数为 `34,560`。物理诊断进一步给出：mass error absolute max=`0.0 kg`，changed particle mass frames=`0`，validity mismatch frames=`0`；初始质量轴有限且为正，总质量=`14.580000378191471 kg`。保存步 wall-chord 检查为 `checked_static_saved_chords`，其结果只是诊断，不构成连续路径物理有效性结论。

## 50-step horizon metrics

| 指标 | step 1 | step 10 | step 20 | step 30 | step 40 | step 50 |
|---|---:|---:|---:|---:|---:|---:|
| position RMSE (m) | 0.000145797902 | 0.001814345414 | 0.003862464562 | 0.005880648219 | 0.007871711007 | 0.010278355770 |
| velocity RMSE (m/s) | 0.001259268549 | 0.005855870770 | 0.012997706788 | 0.024591453436 | 0.040960302755 | 0.059327759176 |

50-step 执行帧平均 position/velocity RMSE 分别为 `0.005000477562474732 m` 与 `0.023321941389603487 m/s`；末帧 ADE 分别为 `0.015237481182968941 m` 与 `0.09644043744273981 m/s`。selection score=`0.94052110744927`，仅是该固定 bounded diagnostic 分数，不能外推为 full-horizon 质量或模型选择结论。物理诊断的 kinetic-energy error absolute max=`0.03050219041798594 J`；wall-chord 命中累计为 `308` 个 saved-chord particle、`0.1299375033704564 kg`。

## 只读边界与 receipt

本任务未修改源码、生产 HDF5、manifest、registry、ledger、denominator、gate 或上级 `PLAN.md`，也未启动 solver/worker/queue；只新增本报告及其 JSON receipt。工作区在任务执行期间观察到另一个既有 docs 提交更新了 `PLAN.md`，本任务未暂存或重写该文件，相关提交边界在 JSON receipt 中单独记录。

机器可读 receipt：[CORE-F3-MLP-HIDDEN16-DIAGNOSTIC-2026-09-28.json](CORE-F3-MLP-HIDDEN16-DIAGNOSTIC-2026-09-28.json)。训练、checkpoint、progress、evaluation、trajectory 与日志均保留在 `/tmp/f3-mlp500-hidden16-seed17-20260928-*`，其 SHA-256 见 receipt。
