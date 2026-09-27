# F3 graph_raw global gradient clip=0.1 真实诊断

## 结论

该候选在 GPU2 上完成了真实 F3 `F3_DEV_00_a0p903125` 的 500-update 训练与 50-step autonomous bounded 评测，但按冻结的严格比较规则拒绝：`candidate_better=false`。它改善了 selection score 和位置误差，却使速度误差变差，因此不保留为后续 full-horizon 候选。

本次严格保持 diagnostic-only：`T1_numerical=false`、`T2_macro=false`、`formal_eligible=false`、`qualification_credit=0`。没有修改生产算法、manifest、registry、ledger、denominator 或 gate，也没有使用未来状态输入。

## 绑定协议与完整性

- 物理 GPU：`CUDA_VISIBLE_DEVICES=2`（进程内报告 `cuda:0`）；case 粒子数 `34560`，登记期望 `835` transitions。
- 协议：`graph_raw`、seed `17`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`、`chunk_size=34560`、`maximum_steps=50`。
- global L2 clipping：`0.1`，插入 `backward()` 与 `optimizer.step()` 之间；训练 `500/500` 完成，`496/500` 更新被裁剪（clip fraction=`0.992`）。
- training：wall `2420.5323821259663 s`，peak GPU memory `1567362048 B`，peak RSS `2777.94140625 MiB`，evidence complete。
- evaluation：bounded 窗口 `50/50` finite/executed，完整登记分母仍为 `835`，因此 `failure_category=maximum_steps_limit` 仅表示窗口右删失，不是 scientific failure；raw error coverage=`0.059880239520958084`。
- HDF5：`51 × 34560` 帧/粒子（含初始帧），position/velocity/mass 全 finite，valid 全 true，particle ID 唯一；时间 `0.0–0.5000171945830302 s`。

## 与 raw500 bounded baseline 比较

| 指标 | baseline | clip=0.1 | 变化 |
|---|---:|---:|---:|
| selection score | 0.9405794502120072 | 0.9405477148942557 | -0.000031735317751469 |
| position RMSE step 50 (m) | 0.010808855234180976 | 0.00852116943672181 | -0.002287685797459166 |
| position RMSE frame mean (m) | 0.006481719115271537 | 0.00450003131706821 | -0.001981687798413327 |
| velocity RMSE step 50 (m/s) | 0.05080001907864858 | 0.05704795039416078 | +0.006247931315512198 |
| velocity RMSE frame mean (m/s) | 0.024221742490882124 | 0.027614788975135203 | +0.003393046484253081 |

冻结规则要求 selection score 严格更低且 bounded/frame-mean 的位置、速度四项均不劣；速度两项变差，故 `candidate_status=rejected_not_better_than_raw500`。

## 证据绑定

machine receipt：[F3-GRAPH-RAW-GRADCLIP010-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-GRADCLIP010-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。

原始运行 receipt：`/tmp/f3-graph-raw-gradclip010-seed17-20260928-receipt.json`，188272 bytes，SHA-256=`802b3bfe154fd7169283f0669d267ed6285b421ed922509e4978f971f0dfd739`。

关键临时产物：

- checkpoint：`/tmp/f3-graph-raw-gradclip010-seed17-20260928-checkpoint.pt`，SHA-256=`d20dcd3f5030f37647892f7d4e62a1741d56487560e4b2fcfc5b35b08d573130`。
- training receipt：`/tmp/f3-graph-raw-gradclip010-seed17-20260928-training.json`，SHA-256=`ea3ce8b4a081745aa729c1f24a99885f5acfa3743cd480d484188251ea6812e4`。
- evaluation JSON：`/tmp/f3-graph-raw-gradclip010-seed17-20260928-evaluate50.json`，SHA-256=`b8733a4913b8cab076d8ce0b86051ba8dfcdb8f94c444e72b37cac5143751a24`。
- trajectory HDF5：`/tmp/f3-graph-raw-gradclip010-seed17-20260928-evaluate50.h5`，SHA-256=`2fe58c4054d702141ab0f0425b0bd1d81086e8e960eb05008c8144b7ccdd7643`。

本提交只新增 machine receipt 与本中文报告；不修改 `PLAN.md`、生产代码、manifest、registry、ledger、denominator 或 gate。
