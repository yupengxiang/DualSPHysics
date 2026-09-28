# F3 graph_raw hidden64 seed17 训练诊断

本报告只登记真实训练阶段的 diagnostic evidence。它不包含 rollout，不授予 formal、T1、T2 或 qualification credit。

## 训练结果

- 物理 GPU：GPU3，`CUDA_VISIBLE_DEVICES=3`；进程内设备为 `cuda:0`，绑定语义已记录在机器报告中。
- 模型：`graph_raw`；seed=`17`；hidden=`64`；`max_neighbors=192`；centers/update=`256`；learning rate=`0.001`；normalization transitions=`16`。
- 训练进度：`500/500`，`evidence_status=complete`，checkpoint verified，参数量 `85,766`。
- 最后记录的 loss MSE：`0.03902001678943634`；记录的 neighbor truncation fraction=`0.0`。
- Core training receipt wall=`2199.7713292408735 s`；外部 `/usr/bin/time` wall=`37:20.67`。
- torch receipt peak allocated GPU memory=`9,713,391,616 bytes`；运行期间 nvidia-smi 采样峰值=`28,917 MiB`，两者语义不同，均未接近 49,140 MiB 总显存。

完整机器报告：`F3-GRAPH-RAW-HIDDEN64-SEED17-TRAINING-DIAGNOSTIC-2026-09-28.json`。

## 可审计 receipt

| artifact | path | SHA-256 |
|---|---|---|
| training receipt | `/tmp/f3-graph-raw500-hidden64-seed17-20260928-gpu3-retry1-training.json` | `dbf6f40fbc1f278fd132b2fed06fcc74bd976401a3afbbb7850e452d029b6fcf` |
| progress | `/tmp/f3-graph-raw500-hidden64-seed17-20260928-gpu3-retry1-training-progress.json` | `a299b8a9fa9b52783f08461afdc6a4a881bf051f3e0436ebc2cfedd51631e07e` |
| checkpoint | `/tmp/f3-graph-raw500-hidden64-seed17-20260928-gpu3-retry1-checkpoint.pt` | `2863fb8737a54b75397b3bb2a74c2bfe61dccccc7e885cbd35a113d50907ca24` |
| training log | `/tmp/f3-graph-raw500-hidden64-seed17-20260928-gpu3-retry1-training.log` | `d600f1195cb23666f660a41ca611851a60707541409aaec40aa292679947b2f2` |

训练使用 train split 的 13,360 个 transitions，确定性选择 16 个 normalization transitions；没有 validation history 或 milestone evaluation，因为本次显式使用 `--validation-every 0 --no-evaluate-milestones`。这不影响训练 receipt 的完成性，但不能把训练 loss 当作 autonomous rollout 质量。

## 只读保护与正式边界

训练前后以下对象哈希保持一致：Core `registry.json`、Core `completion.json`、仓库 `completion.json`、L2 `ledger.json`，以及生产 F3 case HDF5。训练过程没有写入 registry、completion、ledger、formal gate、production HDF5、历史 receipt 或 denominator；本报告本身也不改变这些对象。

`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`qualification_credit=0`、T1/T2 均为 false。full835 rollout 刻意留到本训练-only commit 之后另行执行，rollout 将使用独立报告和独立 commit。

首次裸 `tee` wrapper 在 update 1、receipt 生成前被终止，未生成 checkpoint 或 training receipt；该临时尝试不纳入证据。唯一采纳的 `retry1` 训练完成退出码为 0。

## 验证

- Core 训练相关回归：`116 passed`，退出码 0。
- `py_compile`：`core_learning.py`、`core_models.py`、`core_dataset.py`、`core_contract.py`、full-rollout validator 与 metric summarizer 均通过。
- `git diff --check` 在提交前执行并要求通过。
