# Core continuation status — UPDATE-383（2026-09-28）

## F3 graph_raw hidden16 fresh full835 diagnostic rollout

该批次用于补齐 graph_raw hidden16 三 seed 的真实终态证据链，仍不属于 Core formal training、T1/T2、异机复现或 qualification credit。

| seed | GPU | fresh nonce | namespace | launch state |
|---:|---:|---|---|---|
| 17 | 4 | `d8f2a6c0b4e97135f0c2d8a4e6b1937c` | `/tmp/f3-graph-raw500-hidden16-seed17-full835-nonced8f2a6c0b4e97135f0c2d8a4e6b1937c-*` | running at launch |
| 29 | 5 | `a9c3e7f1b5d02864e2a6c9f3b7d10485` | `/tmp/f3-graph-raw500-hidden16-seed29-full835-noncea9c3e7f1b5d02864e2a6c9f3b7d10485-*` | running at launch |
| 43 | 6 | `e1b7d4a9c2f60835b9e3d7a1c5f02468` | `/tmp/f3-graph-raw500-hidden16-seed43-full835-noncee1b7d4a9c2f60835b9e3d7a1c5f02468-*` | running at launch |

固定合同为 `graph_raw`、hidden `16`、500-update checkpoint、`F3_DEV_00_a0p903125`、split `test`、`maximum-steps=835`、`chunk-size=34560`、`--diagnostic`。所有输出均写入独立 fresh `/tmp` namespace，未覆盖历史 hidden8 或旧 hidden16 输出。

## 终态边界

- 启动时 GPU4/5/6 各有约 43.8 GiB free；显存余量足够，现有任务均保持不动。
- 当前只确认 evaluator 存活，不把 PID、progress 或仍在增长的 trajectory 视为完成，也不读取 live 大文件。
- 自然退出后才允许读取 bounded evaluation JSON，并必须生成独立 HDF5 validator receipt、evaluation identity 和 evaluator/launcher process-exit proof。
- `diagnostic_only=true`、`formal=false`、`T1_numerical=false`、`T2_macro=false`、`qualification=false`、`credit=0`；registry、ledger、denominator、gate、completion 均未修改。

