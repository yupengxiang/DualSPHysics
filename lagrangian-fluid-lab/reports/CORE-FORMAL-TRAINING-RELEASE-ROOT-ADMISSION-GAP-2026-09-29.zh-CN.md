# Core formal-training release/root admission gap inventory

日期：2026-09-29

本轮先审阅了 `core_formal_release_candidate.py`、`core_formal_source_closure_admission_v6.py`、`core_formal_admission_audit.py`、`core_formal_training_readiness_matrix_v1.py` 及其对应测试。结论是：已有实现分别覆盖 release candidate、source closure、跨 manifest admission、以及 9 个 model/seed 的 blocked projection，但没有一个 formal-training 专属的只读 join 同时绑定以下五类输入：

1. formal dataset release manifest；
2. 独立 trusted-root attestation；
3. current source closure；
4. 9 个 model/seed 的 terminal evidence matrix；
5. 固定的 `graph_raw/graph_residual/mlp × 17/29/43` readiness matrix。

新增的 [bounded adapter](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/core_formal_training_release_root_admission_v1.py) 只做 JSON 文件级 digest、角色和 scope join，不重复 case/checkpoint verifier，也不验证 cryptographic root signature。其 [campaign contract](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/learning/core-formal-training-release-root-admission-v1.json) 明确 synthetic-only、planning-only 和默认拒绝。

当前五个实际输入的观察结果：

- `f3-dataset-v2.json` 是 `core.dataset.v2`，32 cases，但 `formal_release=false`；
- v7 source closure 完整且 hash-bound，但 `formal_release=false`、`root_admission_granted=false`、`launch_allowed=false`；
- 现有 root-admission receipt 的 schema 是 `core.formal_source_closure_admission.v2`，不是专用 trusted-root attestation，且仍为 planning-only blocked；
- `registry.json` 是 `core.registry.v1`，`training_runs=[]`，不是 9-row terminal-evidence matrix；
- readiness matrix 的 9 个 scope row 完整且全部 `blocked_fail_closed`，但没有 `trusted_root` 与 `terminal_evidence` 两个 matrix input role。

因此精确 gap 为：

- `FORMAL_DATASET_RELEASE_NOT_GRANTED`；
- `TRUSTED_ROOT_ATTESTATION_MISSING`；
- `TRUSTED_ROOT_AUTHENTICATION_NOT_INTEGRATED`；
- `SOURCE_CLOSURE_RELEASE_OR_ROOT_GATE_MISSING`；
- `TERMINAL_EVIDENCE_MATRIX_MISSING`；
- `TERMINAL_ARTIFACT_REVERIFICATION_NOT_INTEGRATED`；
- `MATRIX_TRUSTED_ROOT_ROLE_REFERENCE_MISSING`；
- `MATRIX_TERMINAL_EVIDENCE_ROLE_REFERENCE_MISSING`。

即使 synthetic fixture 的结构和 digest 全部自洽，adapter 也固定输出 `launch_allowed=false`、`formal_eligible=false`、`credit=0`；caller 自报的 `authenticated`/`signature_verified` 不会被消费成 trusted root。当前完整 JSON 观察见 [gap report](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/reports/CORE-FORMAL-TRAINING-RELEASE-ROOT-ADMISSION-GAP-2026-09-29.json)。

验证：专项测试 `5 passed`；`py_compile` 和 `git diff --check` 通过。没有读取 HDF5/checkpoint，没有启动训练、GPU、worker、queue，也没有写 registry、ledger、denominator、gate、completion、PLAN 或历史 receipt。
