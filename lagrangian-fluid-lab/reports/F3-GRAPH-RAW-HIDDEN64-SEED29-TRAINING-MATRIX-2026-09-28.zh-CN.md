# F3 `graph_raw` hidden64 seed29 training matrix

这是一份训练阶段独立 matrix。当前 matrix 只有一行：真实 F3 `graph_raw`、hidden=`64`、seed=`29`、`max_neighbors=192`，在物理 GPU5 上完成 `500/500` updates。它仅记录 diagnostic evidence，不是 formal training、T1/T2、qualification 或 gate 结果。

## 单行矩阵

| row | model | seed | hidden | max neighbors | updates | final loss MSE | evidence | GPU |
|---|---|---:|---:|---:|---:|---:|---|---:|
| `F3_graph_raw_hidden64_seed29_gpu5` | `graph_raw` | 29 | 64 | 192 | 500/500 | 0.1691545844078064 | `complete` | 5 |

训练 wall=`2174.996464936994 s`，参数量=`85,766`，centers/update=`256`，Adam learning rate=`0.001`，torch peak allocator=`9,914,864,640 B`，peak RSS=`2689.62109375 MiB`，`neighbor_truncation_fraction=0.0`。

GPU 绑定为 `CUDA_VISIBLE_DEVICES=5`，进程内设备 `cuda:0`，GPU 名称为 `NVIDIA RTX 6000 Ada Generation`。没有使用或触碰其他 GPU 的任务控制，也没有终止既有进程。

## 数据与 receipt 绑定

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，SHA-256=`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`。
- reader manifest SHA-256=`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`。
- train split：`16` 个案例、`13,360` 个可用 transitions；normalization 只选取 `16` 个 train transitions，未使用 validation/test state。
- training receipt：`/tmp/f3-graph-raw500-hidden64-seed29-20260928-training.json`，bytes=`10,052`，SHA-256=`b9f9d29d00fc748707386bb8d7067285c09d8f8123e24c838f49399fe44db5c0`。
- completed progress：`/tmp/f3-graph-raw500-hidden64-seed29-20260928-training-progress.json`，bytes=`489`，SHA-256=`0c7cbafeda2d597306e60905f645768a430930a4e08a6aa22572b98f0ccc223f`。
- checkpoint：`/tmp/f3-graph-raw500-hidden64-seed29-20260928-checkpoint.pt`，bytes=`1,107,921`，SHA-256=`6e846dcabf01147796e6004a0f880dc0036a8a7365f35ee046ec8428abde8189`。
- training log：`/tmp/f3-graph-raw500-hidden64-seed29-20260928-training.log`，bytes=`8,711`，SHA-256=`514e59a0c9af63c0e66ff2a32459bb7594a94701883dd719c64dbd686bdfcb9a`。
- 逐项训练审计明细：[F3-GRAPH-RAW-HIDDEN64-SEED29-TRAINING-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-HIDDEN64-SEED29-TRAINING-DIAGNOSTIC-2026-09-28.json)。

## 严格副作用边界

本阶段 rollout 编排已暂停且尚未启动。训练只读真实数据，并把运行产物写到独立 `/tmp` 前缀；没有修改 `registry.json`、`completion.json`、ledger、denominator、formal gate、production HDF5、manifest 或任何历史 receipt。`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`、`qualification_credit=0`。

full835 autonomous rollout 将在本 training-only commit 完成后另行启动，使用独立 rollout JSON/中文报告与独立 commit；本 matrix 不包含 rollout 结果，也不把训练结果宣称为 rollout 或资格证据。
