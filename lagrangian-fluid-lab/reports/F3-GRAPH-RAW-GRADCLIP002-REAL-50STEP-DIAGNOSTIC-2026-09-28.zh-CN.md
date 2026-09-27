# F3 graph_raw global gradient clip=0.02 真实诊断

该候选在物理 GPU5（进程内 `cuda:0`）完成真实 F3 `F3_DEV_00_a0p903125` 的 `500/500` training 和 `50/50` bounded autonomous evaluate。按预先冻结的严格比较规则拒绝：`candidate_better=false`。selection 与位置误差改善，但速度 step/frame-mean 均恶化，不能进入 full-horizon 或 formal follow-up。

结果保持 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。完整 835-transition 分母未完成，`failure_category=maximum_steps_limit` 仅表示 bounded 窗口右删失；raw error coverage=`0.059880239520958084`。没有未来状态输入，也没有修改生产算法、registry、ledger、denominator 或 gate。

## 训练与绑定

- 协议：`graph_raw`、seed `17`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`、chunk size `34560`。
- global L2 clipping：`0.02`，插入 `backward()` 与 `optimizer.step()` 之间；`500/500` 更新触发，clip fraction=`1.0`，pre-clip L2 mean/max=`0.4602750185281038/1.4782127141952515`。
- training：wall `2399.7526227841154 s`，peak GPU memory `1567362048 B`，peak RSS `2768.4296875 MiB`，evidence complete。
- bounded evaluation：`50/50` finite/executed，完整登记分母仍为 `835` transitions，future-state inputs=`false`。

## 与 raw500 bounded baseline 比较

| 指标 | raw500 baseline | clip=0.02 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405424994733336 | -0.00003695073867360232 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.008429603631263867 | -0.0023792516029171092 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.00443947802426087 | improved |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.056499301985959725 | +0.005699282907311143 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.0272971097589119 | worse |

冻结规则要求 selection score 严格更低且 bounded/frame-mean 的位置、速度四项均不劣；速度两项变差，故 `candidate_status=rejected_not_better_than_raw500`。

## 证据绑定

machine summary：[F3-GRAPH-RAW-GRADCLIP002-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-GRADCLIP002-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。原始运行 receipt：`/tmp/f3-graph-raw-gradclip002-seed17-20260928-receipt.json`，188271 bytes，SHA-256=`14da2b56ec93009ee0a0aea8719fd1e61d7772ce9788a547b68499043b451c0c`。

关键临时产物：

- checkpoint：`21d1d29871fefd0f1aa581dab877bfe5c540c2c759b2887226b0eba2db357dfc`
- training JSON：`b91cba250d03907b7039bf60f54256f6a38beffcc0012ac0d27851deae9a5656`
- evaluation JSON：`dd6cfc61c90e8cc9fd9822e95ec615b8af8723e59864d8acf0278eb8a4a1a0a9`
- trajectory HDF5：`9d53b4205ef19755c3b8ceea683317ff3eaee00bcfcfd735e00a79ca78187f81`
- training-progress：`2ea22e8014a2a200a78d2c2270842a2351952f3aecb736affa04b891b69f0069`
- evaluation-progress：`2a770227a5c93898f4494f0411fe1f292c79fdaf0cbac2918740e4f22b77478b`
- run log：`7f1fdf35c43da81c0848c42d4409cd3a8cac5da86f01628966f256b91354239a`

本记录只保留诊断证据；不修改生产代码、manifest、registry、ledger、denominator 或 gate。
