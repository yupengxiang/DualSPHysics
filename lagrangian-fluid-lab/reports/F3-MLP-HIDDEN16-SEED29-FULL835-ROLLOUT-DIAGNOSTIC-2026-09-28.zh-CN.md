# F3 MLP hidden16 seed29 full835 rollout 诊断

本次独立诊断完成了真实 F3 案例 `F3_DEV_00_a0p903125` 的 `500/500` 训练和完整 `835/835` autonomous rollout（836 帧）。结果仅为 diagnostic evidence，不是正式训练、资格或 gate 证据。

## 协议与完整性

- 模型：`mlp`，seed=`29`，hidden=`16`，centers/update=`256`，learning rate=`0.001`，Adam。
- `max_neighbors=192`，normalization transitions=`16`，case=`F3_DEV_00_a0p903125`，GPU=`0`（RTX 6000 Ada）。
- 训练 evidence `complete`，checkpoint `verified=true`，500 updates，1,574 参数。
- 评测执行 `835/835` transitions、`836/836` trajectory frames；HDF5 validator `passed=true`、`complete=true`、`tail_frame_count=0`。
- 全场 position/velocity finite，valid 全为 true，mass 正且静态，`future_state_inputs=false`，raw coverage=`1.0`，无执行失败。

## 指标

| 指标 | step 50 | step 835 |
|---|---:|---:|
| position RMSE (m) | 0.01159946807609371 | 1.415288531359932 |
| velocity RMSE (m/s) | 0.05994632341582491 | 2.294004799758539 |

- selection score=`0.2535846751081573`。
- raw frame-mean position/velocity RMSE=`0.3577475044359603 m / 0.43949690343917935 m/s`。
- 最大 kinetic-energy error=`108.77321551736961 J`；最大质量误差=`0 kg`；validity mismatch=`0`。
- 末帧 FDE：position=`2.114685539149334 m`，velocity=`2.124600214203112 m/s`。

长时域误差明显增长，因此当前 checkpoint 仍不是合格模型；这是完整、可审计的非正式诊断结果。

## 资格边界

`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、credit=`0`。本次未修改源码、生产 HDF5、manifest、registry、ledger、denominator 或 gate，也未终止其他进程。

机器 receipt 与产物哈希见同名 JSON 报告；临时训练、评测和轨迹文件均保留在 `/tmp` 前缀下。
