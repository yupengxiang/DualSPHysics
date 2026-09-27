# F3 graph_raw global gradient clip=0.03 真实诊断

该候选在物理 GPU0（进程内 `cuda:0`）完成真实 F3 `F3_DEV_00_a0p903125` 的 `500/500` training 和 `50/50` bounded autonomous evaluate。按预先冻结的严格比较规则拒绝：`candidate_better=false`。selection 与位置误差改善，但速度 step/frame-mean 均恶化，不能进入 full-horizon 或 formal follow-up。

结果保持 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。完整 835-transition 分母未完成，`failure_category=maximum_steps_limit` 仅表示 bounded 窗口右删失；raw error coverage=`0.059880239520958084`。没有未来状态输入，也没有修改生产算法、registry、ledger、denominator 或 gate。

## 训练与绑定

- 协议：`graph_raw`、seed `17`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`、chunk size `34560`。
- global L2 clipping：`0.03`，插入 `backward()` 与 `optimizer.step()` 之间；`500/500` 更新触发，clip fraction=`1.0`，pre-clip L2 mean/max=`0.46043046067655086/1.4792309999465942`。
- training：wall `2427.405565739842 s`，peak GPU memory `1567362048 B`，peak RSS `2780.5078125 MiB`，evidence complete。
- bounded evaluation：`50/50` finite/executed，完整登记分母仍为 `835` transitions，future-state inputs=`false`。

## 与 raw500 bounded baseline 比较

| 指标 | raw500 baseline | clip=0.03 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405423981523842 | -0.00003705205962301061 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.008424329625019048 | -0.0023845256091619277 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.004436232412854293 | improved |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.056493143551548726 | +0.0056931244729001435 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.027297769743834133 | worse |

冻结规则要求 selection score 严格更低且 bounded/frame-mean 的位置、速度四项均不劣；速度两项变差，故 `candidate_status=rejected_not_better_than_raw500`。

## 证据绑定

machine summary：[F3-GRAPH-RAW-GRADCLIP003-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-GRADCLIP003-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。原始运行 receipt：`/tmp/f3-graph-raw-gradclip003-seed17-20260928-receipt.json`，188256 bytes，SHA-256=`43b0b5a69f0da42a1bd89e182a97978f4a9b3e2a61eb11a30abe10ce670803b1`。

关键临时产物：

- checkpoint：`d4cbd104d5e11bbf2d0619abac0aad57e1e6237f923ec940dfbda3d75b5c496d`
- training JSON：`d36bbb45c176cf1f2af8e687fa46775917fb2a944d88fa1767bb34e606794d59`
- evaluation JSON：`cb526a76f570b9958865b99e72db400a97d4bec7f099b6c71b5d9f887476b95f`
- trajectory HDF5：`dcdee4a91e8abb25af11ede39f12c37d4984bce69f8012a169fcd74f23463ff8`
- training-progress：`8d203122d214a88c6749d794be81dae843d3bcf2d683a027b54d1ed25356bca8`
- evaluation-progress：`2f644935e8ca475a2f78e3ffaace31ce187519da9f8cfa0675e8ba9cd5788f36`
- run log：`e439b653db05623c9173c07e6e20438896bf2abc98f8bfb8c52a867eaa446ad8`

本记录只保留诊断证据；不修改生产代码、manifest、registry、ledger、denominator 或 gate。
