# F3 graph_raw hidden64 seed43 GPU7 训练诊断

本报告只登记真实训练阶段的 diagnostic evidence。训练已完成 `500/500`，但本报告不包含 rollout，也不授予 formal、T1、T2 或 qualification credit。full835 autonomous rollout 将在本 training-only commit 之后使用独立 `/tmp` 前缀、报告和 git commit。

## 训练结果

- 物理 GPU：GPU7，`CUDA_VISIBLE_DEVICES=7`；进程内设备为 `cuda:0`，绑定语义为环境变量将物理 GPU7 映射到进程本地设备。
- 模型：`graph_raw`；seed=`43`；hidden=`64`；`max_neighbors=192`；centers/update=`256`；Adam learning rate=`0.001`；normalization transitions=`16`。
- 训练进度：`500/500`，`evidence_status=complete`，checkpoint verified，参数量 `85,766`。
- 最后记录的 loss MSE：`0.1778753250837326`；neighbor truncation fraction=`0.0`。
- validation snapshot：update `500`，4 transitions/256 centers，RMSE=`0.6622344717492769`；这不是 autonomous rollout 质量指标。
- Core training receipt wall=`2195.344030522974 s`；torch receipt peak allocated GPU memory=`9,822,246,400 bytes`；peak RSS=`3004.88671875 MiB`。

## 可审计 receipt

| artifact | path | bytes | SHA-256 |
|---|---|---:|---|
| training receipt | `/tmp/f3-graph-raw500-hidden64-seed43-gpu7-training.json` | 10,667 | `faf092a825821d1b435c25f5767b9bbea6d474491543dffc2c639b64b6035490` |
| completed progress | `/tmp/f3-graph-raw500-hidden64-seed43-gpu7-training-progress.json` | 475 | `616b0938ac5c203bd1e2fb93aee4a1b441de6a63597173fdd29d3ceff77917fb` |
| checkpoint | `/tmp/f3-graph-raw500-hidden64-seed43-gpu7-checkpoint.pt` | 1,107,629 | `c2d53f58a6058e7edb0627561866e72c6777b792a7286f40bca527ce2f381e8b` |
| training log | `/tmp/f3-graph-raw500-hidden64-seed43-gpu7-training.log` | 9,330 | `e4f629191fb6484be46dcaac2ceff63e133381aaa99e4b7eb3ee895c1b79d525` |

训练使用 train split 的 `13,360` 个 transitions，确定性选择 `16` 个 normalization transitions，采样器 draws=`500`；没有使用 test state，也没有在本训练任务中执行 rollout。

## 只读保护与正式边界

训练前后以下对象哈希保持不变：Core `registry.json`、Core `completion.json`、仓库 `completion.json`、L2 `ledger.json`，以及生产 F3 case HDF5。训练产物全部写入独立 `/tmp/f3-graph-raw500-hidden64-seed43-gpu7-*` 前缀；没有修改 registry、completion、ledger、formal gate、production HDF5、历史 receipt、denominator 或 manifest。

`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`qualification_credit=0`、T1/T2 均为 false。训练指标不能外推为 autonomous rollout 质量或正式资格结果。

## 验证

- Core 训练相关回归：`116 passed`，失败 `0`，exit code `0`。
- `py_compile`：`core_learning.py`、`core_models.py`、`core_dataset.py`、`core_contract.py`、full-rollout HDF5 validator 与 metric summarizer 均通过。
- `git diff --check`：通过，exit code `0`。

机器报告：[F3-GRAPH-RAW-HIDDEN64-SEED43-GPU7-TRAINING-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-HIDDEN64-SEED43-GPU7-TRAINING-DIAGNOSTIC-2026-09-28.json)。
