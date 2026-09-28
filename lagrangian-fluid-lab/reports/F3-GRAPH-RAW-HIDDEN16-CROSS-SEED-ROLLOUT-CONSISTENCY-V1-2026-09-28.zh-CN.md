# F3 `graph_raw` hidden16 三 seed rollout 一致性矩阵 V1

机器报告：[`F3-GRAPH-RAW-HIDDEN16-CROSS-SEED-ROLLOUT-CONSISTENCY-V1-2026-09-28.json`](F3-GRAPH-RAW-HIDDEN16-CROSS-SEED-ROLLOUT-CONSISTENCY-V1-2026-09-28.json)

## 结论

当前结果为 `blocked_fail_closed`，不是 qualification 结论。适配器只读取有界 JSON 收据和小文件元数据；没有打开 manifest、case HDF5、checkpoint、trajectory 或 progress，也没有启动 runtime/GPU/worker。

- 目标模型：`graph_raw`、hidden=`16`、updates=`500`。
- seed 集合：`17 / 29 / 43`。
- 固定 rollout 分母：`835 transitions / 836 frames`。
- 结果边界：`diagnostic_only=true`、`formal_eligible=false`、`T1_numerical=false`、`T2_macro=false`、`qualification=false`、`qualification_credit=0`、`credit=0`。
- registry、ledger、denominator、gate、completion mutation 均为 `0` 或 `false`。

## 收据绑定

- 三个 training JSON 均按 `core.training.v1` 检查，并绑定 model family、seed、hidden、updates、checkpoint path+SHA 和 shared config。
- seed17 的 hidden16 terminal rollout summary 已绑定为 terminal diagnostic，并检查 `835/836`、fresh output identity、future-state=false 及零 credit markers。
- seed29 的现有候选 schema 为 `core.f3.graph_raw.real_full835_rollout_diagnostic.summary.v1`，其历史协议是 hidden8，不是目标 hidden16；因此明确 rejected，不能替代缺失的 hidden16 terminal receipt。
- seed43 的现有 hidden16 summary 含重复 JSON object key `qualification`，严格 JSON 解析拒绝读取；因此保持 missing/rejected，不修写历史收据。

## 外部依赖

仍有外部依赖：需要一个可严格解析、终态、hidden16、seed29 的 rollout receipt，以及修复/重新提供无重复 key 的 seed43 hidden16 terminal summary。获得它们后可通过同一脚本的 `--rollout SEED=PATH` 重新绑定；在此之前不会推进为完整三 seed 矩阵，也不会产生任何 T1/T2 或 qualification credit。

本报告不修改 `PLAN.md`，不改 registry、ledger、denominator 或 gate。
