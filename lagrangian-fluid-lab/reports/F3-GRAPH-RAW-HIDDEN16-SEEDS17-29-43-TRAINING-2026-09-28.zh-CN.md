# F3 graph_raw hidden16 三种子训练矩阵（2026-09-28）

三路真实 F3 `graph_raw`/hidden16/cap192 训练均完成 `500/500`，checkpoint verified，参数量均为 `6,086`，neighbor truncation 均为 `0`。这是一份独立的 training evidence；full835 rollout 正在并行执行，因此本报告不授予正式资格、T1/T2 或 credit。

| seed | wall (s) | last loss MSE | validation RMSE | peak GPU bytes | checkpoint SHA 前缀 |
|---:|---:|---:|---:|---:|---|
| 17 | 2204.8234 | 0.0772837251 | 0.7626094110 | 2,731,527,680 | `19cf88df…` |
| 29 | 2302.1890 | 0.2717114687 | 0.8294239069 | 2,786,759,168 | `4cd9dc78…` |
| 43 | 2185.9195 | 0.1758372784 | 0.7760517751 | 2,762,580,992 | `c979614f…` |

固定设置为 centers=256、max_neighbors=192、learning rate=0.001、normalization transitions=16、无 gradient clipping、validation transitions=4。训练证据完整，但 manifest `formal_release=false`，所以 `formal_eligible=false`、qualification/T1/T2=false、credit=0；最终判断等待对应的完整 autonomous rollout。

JSON machine receipt 同目录记录了三个训练 receipt、progress receipt、checkpoint SHA-256、初始化参数 digest 和资源峰值。
