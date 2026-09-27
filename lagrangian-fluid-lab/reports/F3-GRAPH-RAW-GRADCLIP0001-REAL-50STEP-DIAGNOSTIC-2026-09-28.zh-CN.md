# F3 graph_raw global gradient clip=0.001 真实诊断

该候选在物理 GPU7（进程内 `cuda:0`）完成真实 F3 `F3_DEV_00_a0p903125` 的 `500/500` training 和 `50/50` bounded autonomous evaluate。按预先冻结的严格比较规则拒绝：`candidate_better=false`。selection 与位置误差改善，但速度 step/frame-mean 均恶化，不能进入 full-horizon 或 formal follow-up。

结果保持 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。完整 835-transition 分母未完成，`failure_category=maximum_steps_limit` 仅表示 bounded 窗口右删失；raw error coverage=`0.059880239520958084`。没有未来状态输入，也没有修改生产算法、registry、ledger、denominator 或 gate。

## 训练与绑定

- 协议：`graph_raw`、seed `17`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`、chunk size `34560`。
- global L2 clipping：`0.001`，插入 `backward()` 与 `optimizer.step()` 之间；`500/500` 更新触发，clip fraction=`1.0`，pre-clip L2 mean/max=`0.45517885258793833/1.4396220445632935`。
- training：wall `2461.574671529932 s`，peak GPU memory `1567362048 B`，peak RSS `2786.19921875 MiB`，evidence complete。
- bounded evaluation：`50/50` finite/executed，完整登记分母仍为 `835` transitions，future-state inputs=`false`。

## 与 raw500 bounded baseline 比较

| 指标 | raw500 baseline | clip=0.001 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405432484265196 | -0.000036201785487577354 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.008582364506748635 | -0.002226490727432341 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.004514956469560048 | improved |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.05661218180931974 | +0.005812162730671158 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.027122245316117795 | worse |

冻结规则要求 selection score 严格更低且 bounded/frame-mean 的位置、速度四项均不劣；速度两项变差，故 `candidate_status=rejected_not_better_than_raw500`。

## 证据绑定

machine summary：[F3-GRAPH-RAW-GRADCLIP0001-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-GRADCLIP0001-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。原始运行 receipt：`/tmp/f3-graph-raw-gradclip0001-seed17-20260928-receipt.json`，188276 bytes，SHA-256=`e10d639f1c3cb12bf5e57b63f2c45fefd737b7b82826c0e6715a7100c28eff00`。

关键临时产物：

- checkpoint：`6bf8719b35b724b4e59d09cd2ae9cf7e1e55bf4e3236f0d80dd217af446e28df`
- training JSON：`f8768b1aca0e7f8a77effb14cc3abcae074229ef269a42716c00b5d8675eff4c`
- evaluation JSON：`f4dc3b696409d30d9e4516d5be7f5e07555f0752e33693104680165ddd145fe0`
- trajectory HDF5：`3b5a224b6f881ef121748d5b54518f137154c345878481b11bd2bea0972dec90`
- training-progress：`689650b8eb0f856468f25e8dd4773732cf57235a0ce095ebfa6da756d5c7575f`
- evaluation-progress：`edff4bf76e6ef73d68f504fc18ecb1a0f3dcdf9d36349c5912f5f90f9995b6ff`
- stdout log：`09aaca6d125fd4e3df164a44956c0f9baed16bca443642fad9a1ee7f6d2b168f`

本记录只保留诊断证据；不修改生产代码、manifest、registry、ledger、denominator 或 gate。
