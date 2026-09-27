# F3 graph_raw global gradient clip=0.01 真实诊断

## 结论

该候选完成了真实 F3 `F3_DEV_00_a0p903125` 的 500-update 训练和 50-step autonomous 短窗评测，但按预先冻结的严格比较规则拒绝：`candidate_better=false`。它只改善位置误差，速度误差变差，因此不保留为后续 full-horizon 候选。

本次仍是 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。没有修改生产算法、manifest、registry、ledger、denominator 或 gate，也没有使用未来状态输入。

## 绑定协议与执行结果

- case：`F3_DEV_00_a0p903125`；粒子 `34560`；期望 `835` transitions；`graph_raw`、seed `17`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`。
- global L2 clipping：`0.01`，插入 `backward()` 与 `optimizer.step()` 之间；500/500 update 被裁剪，clip fraction=`1.0`，pre-clip L2 mean/max=`0.45975428822636605/1.4765514135360718`。
- training：`500/500`，wall `2575.0460803888272 s`，peak GPU memory `1567362048 B`，peak RSS `2765.98046875 MiB`，evidence complete。
- evaluation：请求窗口 `50/50` finite/executed，wall `1006.2 s`；完整登记分母仍为 `835` transitions，故 failure category=`maximum_steps_limit`，raw error coverage=`0.059880239520958084`。

## 与 raw500 bounded baseline 比较

| 指标 | baseline | clip=0.01 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405440786706813 | -0.000035371541325823762 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.008471783800619245 | -0.0023370714335617312 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.004470030799729434 | improved |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.05661942282947159 | +0.005819403750823009 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.027352964445654483 | worse |

冻结规则要求 selection score 严格更低且四项 bounded/frame-mean position/velocity 指标均不劣；速度两项变差，故 `candidate_status=rejected_not_better_than_raw500`。

## 证据绑定

原始完整 receipt 仍保存在 `/tmp/f3-graph-raw-gradclip001-seed17-receipt-20260928.json`，bytes=`188251`，SHA-256=`0770f3d242ea75a1020d384c944ab9646b6acfdc88e6023ff62f121caa72a2b3`。关键产物：

- checkpoint：`/tmp/f3-graph-raw-gradclip001-seed17-20260928.pt`，SHA-256=`bc71065d97afd1c939bd3dad610c6e67f62cf4c5ecebdd42ba3524c0836e4a99`。
- training receipt：`/tmp/f3-graph-raw-gradclip001-seed17-training-20260928.json`，SHA-256=`4241ef42e7ca32ce61f0014f5830e1ed5b75dae848036dcc6107f5950ce14e6e`。
- evaluation JSON：`/tmp/f3-graph-raw-gradclip001-seed17-evaluate50-20260928.json`，SHA-256=`7481e2fe26e49bde08c04abf14f3537158da803584caa70011c411db7a08d6b7`。
- trajectory HDF5：`/tmp/f3-graph-raw-gradclip001-seed17-evaluate50-20260928.h5`，SHA-256=`0869ecb31bb0bc910315cb3ec8c21dcd7631294efdc62378e8f463e770d1ddb6`。

原始 source/case SHA、manifest SHA、baseline SHA 和 side-effect flags 见同一 receipt；本报告不改写该不可变诊断凭据。
