# F3 `graph_raw` hidden64 seed29 训练诊断

本次独立任务已在物理 GPU5 上完成真实 F3 `graph_raw`、hidden=`64`、seed=`29`、`max_neighbors=192` 的 `500/500` 更新训练。结果严格限定为 diagnostic evidence：不是 formal training、不是 T1/T2、不是 qualification，也不产生任何 gate、registry、completion、ledger 或 denominator credit。

## 结果摘要

- GPU：NVIDIA RTX 6000 Ada Generation，物理索引 `5`；启动环境为 `CUDA_VISIBLE_DEVICES=5`，进程内设备为 `cuda:0`。
- 模型：`graph_raw`，seed=`29`，hidden=`64`，参数量 `85,766`，centers/update=`256`，Adam，learning rate=`0.001`。
- 训练：`500/500` updates，receipt `evidence_status=complete`，checkpoint `checkpoint_verified=true`。
- 训练 wall：`2174.996464936994 s`；torch 报告的 peak GPU allocator=`9,914,864,640 B`；peak RSS=`2689.62109375 MiB`。
- 最终 loss MSE：`0.1691545844078064`；`neighbor_truncation_fraction=0.0`。
- 归一化：只使用 train split 的 `16` 个 deterministic evenly-spaced transitions；可用 train transitions=`13,360`，没有使用 validation/test state 做 normalization。
- 本报告不包含 rollout：full835 rollout 会在本训练报告提交后另行执行，并使用独立 rollout 报告与 commit。

## 冻结协议与审计绑定

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；F3 train split 共 `16` 个案例、`13,360` transitions。
- 固定协议：`graph_raw`、seed `29`、updates `500`、hidden `64`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、`max_neighbors=192`。
- 训练命令使用独立 `/tmp/f3-graph-raw500-hidden64-seed29-20260928-*` 前缀，没有覆盖已有 hidden8/hidden16 receipt、checkpoint 或轨迹。
- report baseline commit：`69f62e170666c650a531086808e5f0e1846abf1f`。
- manifest SHA-256：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`。
- reader manifest SHA-256：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`。
- `scripts/core_learning.py` SHA-256：`3eefe1441dabb350182090c3625f24a8209543a4a31d02521f283074c996c27b`。
- `scripts/core_models.py` SHA-256：`20e635ebd25cd511eeff6f84478678d3364608fd86a5d4b67e2aa53a0d88295d`。
- `scripts/core_dataset.py` SHA-256：`65f583b8fcb1c46e56d10506e22aa1e5fa32c7b2631017de85c88b1f6d53f88f`。
- `scripts/core_contract.py` SHA-256：`1866b35259f407e8c0d8b399eb4034eb18cc8b59f4addc1156f20d6777a326bc`。

## 训练 receipt 与 checkpoint

训练 receipt 为 `core.training.v1`，路径为 `/tmp/f3-graph-raw500-hidden64-seed29-20260928-training.json`，SHA-256 为 `b9f9d29d00fc748707386bb8d7067285c09d8f8123e24c838f49399fe44db5c0`，bytes=`10132`。

最终 progress 为 `/tmp/f3-graph-raw500-hidden64-seed29-20260928-training-progress.json`，SHA-256 为 `0c7cbafeda2d597306e60905f645768a430930a4e08a6aa22572b98f0ccc223f`，状态为 `completed`、update=`500`、最后记录 case=`F3_DEV_07_a0p946875`、frame=`172`。

最终 checkpoint 为 `/tmp/f3-graph-raw500-hidden64-seed29-20260928-checkpoint.pt`，`core.checkpoint.v1`，update=`500`，bytes=`1,107,921`，SHA-256 为 `6e846dcabf01147796e6004a0f880dc0036a8a7365f35ee046ec8428abde8189`。

初始化证据记录了训练前构造的参数 digest：
`2b0bdf881196fdc414288dfa95f6872b27e99beaf269fa0c9a2ab073c8d53e0f`，`constructed_before_first_update=true`，`construction_update=0`。

## 可复核的训练轨迹摘要

| update | loss MSE | case | frame | neighbor truncation |
|---:|---:|---|---:|---:|
| 1 | 1.2417172193527222 | `F3_DEV_24_a1p053125` | 796 | 0.0 |
| 100 | 0.6548047065734863 | `F3_DEV_25_a1p059375` | 527 | 0.0 |
| 200 | 0.4787161350250244 | `F3_DEV_24_a1p053125` | 528 | 0.0 |
| 300 | 0.008803218603134155 | `F3_DEV_15_a0p996875` | 6 | 0.0 |
| 400 | 0.25348252058029175 | `F3_DEV_07_a0p946875` | 612 | 0.0 |
| 500 | 0.1691545844078064 | `F3_DEV_07_a0p946875` | 172 | 0.0 |

这些是训练过程的诊断摘要，不是 test rollout 质量指标，也不能外推 full835 误差或 qualification 结果。

## 副作用边界与资格结论

本轮只读取真实 F3 数据并写入 `/tmp` 训练产物以及本报告文件。没有修改 source algorithm、production HDF5、manifest、`registry.json`、`completion.json`、ledger、denominator 或 formal gate；没有启动 solver/worker/rollout，也没有终止其他进程或覆盖历史 receipt。

资格字段固定为：`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`、`qualification_credit=0`。该 checkpoint 仅作为随后独立 full835 autonomous rollout 的输入。

机器可读明细见 [F3-GRAPH-RAW-HIDDEN64-SEED29-TRAINING-DIAGNOSTIC-2026-09-28.json](F3-GRAPH-RAW-HIDDEN64-SEED29-TRAINING-DIAGNOSTIC-2026-09-28.json)。
