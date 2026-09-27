# F3 graph_raw global gradient clip=0.003 真实诊断

该候选在物理 GPU4（进程内 `cuda:0`）完成真实 F3 `F3_DEV_00_a0p903125` 的 `500/500` training 和 `50/50` bounded autonomous evaluate。按冻结的严格比较规则拒绝：`candidate_better=false`。位置指标改善，但速度 step/frame-mean 两项均恶化，不能进入 full-horizon 或 formal follow-up。

结果保持 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。完整 835-transition 分母未完成，evaluation failure=`maximum_steps_limit`，raw error coverage=`0.059880239520958084`；没有未来状态输入，也没有修改生产算法、registry、ledger、denominator 或 gate。

关键训练结果：wall `2431.815250508953 s`，peak GPU memory `1567362048 B`，peak RSS `2789.546875 MiB`，global-L2 clip fraction=`1.0`，pre-clip L2 mean/max=`0.45975428822636605/1.4765514135360718`。

| 指标 | raw500 baseline | clip=0.003 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405454644421986 | -0.00003398576980861989 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.008536639387091776 | -0.0022722158470892 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.00450961044747494 | improved |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.05679172971693826 | +0.005991710638289675 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.02735982051676984 | worse |

原始完整 receipt：`/tmp/f3-graph-raw-gradclip0003-seed17-20260928-receipt.json`，bytes=`188250`，SHA-256=`896ac3230c7c00b9228c43a3ade827ef2ffdf9ae1186e6040425dbc3b6359ae1`。checkpoint SHA-256=`bbfbafd0105ae62a9fb0be1d3375b99f7efa69c7cd014c96cc69ab98dee7279c`；training JSON SHA-256=`2f101ab7781bdd07fa43bbb67bcbf6b4ba77ccf1f9b7fa1e209515e38301b1f3`；evaluation JSON SHA-256=`fed37667a3f8428cb3fdd226309945445e8f71b69bdb2b26d841fb6072d4cd3c`；trajectory HDF5 SHA-256=`d8aa850a6ce44a7b97cddb32374f29f60ec15901f175f98cc8aabb051a6bc637`。
