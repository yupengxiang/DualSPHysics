# T1 observed model case-run evidence binding

- 状态：`typed_evidence_gap_fail_closed`；typed projection：`True`；fail-closed：`True`
- Core observed T1 case-runs：`0/432`；缺口：`432`
- T1：`false`；formal：`false`；credit：`0`；本 intake 不写入 Core 状态。

## 真正未覆盖的 typed binding

每个未来 row 必须把 `family/scope/case/seed` 同时绑定到 matrix digest、formal model identity、source-reader receipt、natural-exit terminal receipt 与四个产物 digest；现有 matrix/audit 没有这一整行 observed receipt。

| family | matrix planned/observed terminal | typed rows |
|---|---:|---:|
| F3 graph_raw | 96/0 | 96 |
| F3 graph_residual | 96/0 | 96 |
| F3 mlp | 96/0 | 96 |
| F4 T1 | 144/0 | 144 |

## 阻塞原因

- `NO_OBSERVED_MODEL_CASE_RUN_RECEIPTS`：F3/F4 matrices and the existing F4 denominator audit contain no observed model case-run receipt.
- `MATRIX_PLANS_ARE_NOT_TERMINAL_EVIDENCE`：planned case×seed rows expose output placeholders but no natural-exit terminal receipt cross-bound to a source-reader receipt.
- `F3_TRAINING_MATRIX_IS_DIAGNOSTIC_FRONTIER_ONLY`：current-manifest matrices plan diagnostic 500-update identities while the formal launch contract requires 32000-update model/seed identities.
- `F4_SOURCE_READER_MANIFEST_SHA_DRIFT`：F4 material matrix records reader manifest SHA mismatch; a future source-reader receipt must bind the exact current manifest digest.
- `F4_MATERIAL_SIDECAR_IS_NOT_MODEL_CASE_RUN_EVIDENCE`：the F4 sidecar matrix is a material/trajectory contract and has zero complete sidecars/model case-run receipts.
- `FORMAL_CAPACITY_AND_LAUNCH_NOT_ADMITTED`：formal capacity evidence is false and the nine-run launch contract is proposal-only/launch-disallowed.

## 边界

只读取有界 JSON 元数据；没有打开/重哈希 HDF5、checkpoint 或 trajectory，没有启动 solver/worker/GPU/queue，也没有修改 registry、ledger、denominator、gate、completion 或 PLAN。

完整 candidate 即使通过本 projection，也只会得到 `typed_binding_ready_zero_credit`，不会被计为 observed/T1。
