# F4 Macro-T2 Sidecar Preflight v2（2026-09-23）

本版本保留 v1 历史回执，并把已有 F4 JSON validator 接入逐案例 preflight。没有打开 active H5、启动 solver/GPU/queue，或修改 registry、ledger、matrix 和科学分母。

当前结论：`T2_macro=false`、`T2_path=false`、`qualification_claim=none`。

## Validator wiring

- validator：`scripts/core_material_acceptance.py::evaluate_f4_tallwall120_diagnostic_json`
- registered case sidecars：`6`
- validator invocations：`6`
- blocked cases：`6`；passed cases：`0`
- formal acceptance receipts：`0`

逐案例调用已完成，但现有 sidecar 是旧版摘要或诊断数据，不能满足 `core.material.f4.tallwall120.diagnostic.v1` 的完整 identity/hash/event/tolerance contract；因此全部 fail-closed，不产生 T2 credit。

## Scientific boundary

unknown、right-censor、residence/事件容差、checkpoint/generation、33 行矩阵和正式 receipt 仍分别验收；source 可用或 preflight 通过不等于材料资格。

Evidence：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-macro-t2-sidecar-preflight-v2-20260923.json`
