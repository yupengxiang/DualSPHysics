# R3 G1 lineage contract diagnostic

状态：**candidate-only 诊断，不是正式验收**。本检查只构造 Python records；不调用 GenCase、DualSPHysics 或 GPU。

## 结论

当前 HEAD 的 W08 generator 生成 204 张卡片，W08 `audit()` 通过，W10 `validate_split_lineage()` 也通过；持久化设计文件与 generator 输出一致：`True`。因此当前树中没有再观察到旧的拒绝。

审阅者指出的历史不一致可稳定复现：把当前 204 张物理卡投影到 pre-918 W08 的 family-shared `lineage_group_id` 后，旧的 W08 signature-only audit 仍通过，而 W10 validator 拒绝：

- W08 signature-only audit：`pass`，196 个 execution units，无跨 split signature leakage。
- W10 `validate_split_lineage`：`reject`，原因是 family lineage 同时出现在多个 split。
- 复现中的跨 split lineage 数：`4`（F1、F2、F3、F6 各一条）。

根因是两个阶段曾使用不同的 split key：W08 只看 `execution_unit_id`，W10 看 `lineage_group_id`。当前树已经把 W08 audit 接到 W10 primitive，并将 lineage 按 exact physical case 生成；本目录保留的是回归证据，不改写既有语义。

## candidate-only contract 建议

在 W08 materialization 前运行 W10 primitive，并额外要求 W08 卡片具备完整的 `physical_case_id`、`lineage_group_id`、`execution_unit_id` 和 `split`；同一 physical case 必须唯一映射到一个 split、lineage 和 execution unit，反向 execution 映射也必须唯一。`paired_background_id` 继续允许按干预协议跨 split 复用，不作为 split key。

这套额外检查仅在新增脚本中作为候选适配器演示，**未修改** `scripts/protocol_metrics.py`、`scripts/w08_generalization_design.py`、upstream solver 或发布门禁。

## 证据入口

- `scripts/r3_g1_lineage_contract.py`
- `tests/test_r3_g1_lineage_contract.py`
- `scripts/w08_generalization_design.py`
- `scripts/protocol_metrics.py::validate_split_lineage`
- 历史修复边界：`91847d6`、`72c353f`
