# F3 batch closure binding v1

状态：`synthetic-only`、JSON-only、诊断闭合；不构成资格、正式证据或任何 credit。

## 本次交付

新增 `scripts/f3_rollout_batch_closure_binding_v1.py`，作为以下四类 JSON 与现有 batch aggregator 之间的只读绑定层：

- `core.f3.vram_batch_launch_receipt.v1`
- `core.training.v1`
- 每个 case 独立的 `core.evaluation.v1`
- 每个 case 独立的 `core.rollout.progress.v1`

聚合阶段复用现有 `f3_rollout_batch_receipt_v1.aggregate_rollout_files`，不修改 reducer。

适配器校验 model、seed、hidden、training updates、checkpoint path/SHA、835 transitions/case、case 集合、fresh output prefix、evaluation/progress 路径共识，以及 diagnostic/formal/zero-credit flags。训练 hidden 还与 `evidence.initialization` 交叉校验；若 evaluation 携带 embedded binding，也必须与 launch/case binding 完全一致。

## Synthetic 机器报告

机器报告：`F3-ROLLOUT-BATCH-CLOSURE-BINDING-V1.json`

- synthetic cases：3
- 状态：1 completed、1 running、1 failed
- denominator：`3 × 835 = 2505`
- executed transitions：875
- full-denominator cases：1
- 复用 aggregator：是
- qualification/formal/credit：均为 false/0
- HDF5、manifest、checkpoint，以及声明的 trajectory/progress 输出路径：均未打开（输入 JSON sidecar 只按 JSON 读取）
- live jobs、runtime、registry、ledger、gate、denominator mutation：均未发生

## Fail-closed 覆盖

synthetic tests 覆盖 launch model/checkpoint SHA、training hidden/updates/checkpoint path、evaluation output prefix、progress denominator/status、case 集合、embedded case SHA、formal claim、缺少 live terminal JSON 等漂移。任意不一致都返回 `fail_closed=true`，并保持 zero credit。

## 边界

此层只读取调用方显式提供的 JSON；不会为了等待或生成 terminal JSON 而启动、停止或探测作业，也不会打开任何 HDF5。`--case-binding` 中的 case path/SHA 是声明性输入，不代表文件已被读取。它不检查 scientific eligibility，不修改 gate/ledger/registry，也不把 835 完整度转换为资格。

训练 receipt 的 `config.manifest_sha256` 仅做格式校验并原样保留；当前仓库中它与 launch manifest SHA 属于不同语义的 manifest 声明，因此本适配器不把二者强行判为同一值。

## 调用入口

```bash
python scripts/f3_rollout_batch_closure_binding_v1.py \
  --launch-receipt <launch.json> \
  --training-receipt <training.json> \
  --evaluation <CASE_ID> <evaluation.json> \
  --progress <CASE_ID> <progress.json> \
  --case-binding <CASE_ID> <case-path> <case-sha256> \
  --output <closure.json>
```

缺失、重复、跨来源冲突或声明了 formal/credit 的输入均 fail-closed；成功结果仍只表示 JSON batch closure binding。
