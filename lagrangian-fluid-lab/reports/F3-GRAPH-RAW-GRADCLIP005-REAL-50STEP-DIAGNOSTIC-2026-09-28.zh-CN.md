# F3 graph_raw global gradient clip=0.05 真实诊断

该候选在物理 GPU6（进程内 `cuda:0`）完成真实 F3 `F3_DEV_00_a0p903125` 的 `500/500` training 和 `50/50` bounded autonomous evaluate。按预先冻结的严格比较规则拒绝：`candidate_better=false`。selection 与位置误差改善，但速度 step/frame-mean 均恶化，不能进入 full-horizon 或 formal follow-up。

结果保持 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。完整 835-transition 分母未完成，`failure_category=maximum_steps_limit` 仅表示 bounded 窗口右删失；raw error coverage=`0.059880239520958084`。没有未来状态输入，也没有修改生产算法、registry、ledger、denominator 或 gate。

## 训练与绑定

- 协议：`graph_raw`、seed `17`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`、chunk size `34560`。
- global L2 clipping：`0.05`，插入 `backward()` 与 `optimizer.step()` 之间；`500/500` 更新触发，clip fraction=`1.0`，pre-clip L2 mean/max=`0.46055133429169653/1.4801335334777832`。
- training：wall `2436.483587903902 s`，peak GPU memory `1567362048 B`，peak RSS `2780.36328125 MiB`，evidence complete。
- bounded evaluation：`50/50` finite/executed，完整登记分母仍为 `835` transitions，future-state inputs=`false`。

## 与 raw500 bounded baseline 比较

| 指标 | raw500 baseline | clip=0.05 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405423735215813 | -0.00003707669042585238 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.008421365334596673 | -0.0023874898995843025 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.004434702809851045 | improved |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.05649267492612109 | +0.005692655847472507 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.027300375302843037 | worse |

冻结规则要求 selection score 严格更低且 bounded/frame-mean 的位置、速度四项均不劣；速度两项变差，故 `candidate_status=rejected_not_better_than_raw500`。

## 证据绑定

machine summary：[F3-GRAPH-RAW-GRADCLIP005-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-GRADCLIP005-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。原始运行 receipt：`/tmp/f3-graph-raw-gradclip005-seed17-20260928-receipt.json`，188260 bytes，SHA-256=`3a4354479f944dff19306d60a788883b77a154c85470af4d81f017009d2a908d`。

关键临时产物：

- checkpoint：`bc61ddb954c2b4d61dc05d5fdaf23f36b4ccb4ae044c03da477f49d945b6dfa4`
- training JSON：`03c1104f62a77383bef99ce419d6a1347386f37bc71eedaf05ffe5063ad5ea17`
- evaluation JSON：`636a86ed25065801741488ed896c07a4ea54eed234b9aa196542181eb377b68b`
- trajectory HDF5：`dcd84dbc22564fb381a68e33dbe3b123106cf7362ca4024437d3aa7b2e95d52a`
- training-progress：`936e926ddd15017e627ccf2577d9c8f37dcdab34ab38cd6907cbaf3b8678c357`
- evaluation-progress：`217f2e0bf1bea6948939f1d0f9d97f9b0612f42df2abdbf8e69890185f30853b`
- stdout log：`5b6f9ae7a2a1354be3e2bd1448e5e986116e84ebf80c38af8267f080b72c923e`

本记录只保留诊断证据；不修改生产代码、manifest、registry、ledger、denominator 或 gate。
