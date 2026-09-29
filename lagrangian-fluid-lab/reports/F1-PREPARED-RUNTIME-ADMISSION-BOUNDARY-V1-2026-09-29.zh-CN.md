# F1 prepared → runtime admission boundary V1

状态：`blocked_fail_closed`。

这是一个比 readiness bridge 更窄的接口组件：它只从当前 F1 prepared matrix、prepared-only job manifest、Definition 和 observer calibration 的 bounded JSON 元数据推导 15 行 row binding，并定义未来 admission envelope 的严格字段边界。不打开 cell `prepared.json`、result/audit/observations/trajectory，不跟随嵌套路径，不启动 GenCase/native/solver/worker/GPU/queue，也不修改 PLAN、registry、ledger、denominator、gate 或 completion。

## 当前接口投影

- boundary：`F1_H1_prepared_to_runtime_admission_v1`；prepared rows=`15`，runtime rows admitted=`0`。
- matrix/design digest 和 observer revision/code/layout digest 已从 bounded metadata 绑定；这不是 trusted source/runtime attestation。
- 15 个 `prepared_row_sha256` 已派生用于未来逐行 admission binding；当前没有 admission envelope、runtime receipt、trusted root review 或 execution authorization。
- 所有 caller-supplied authority 均拒绝晋级；`formal=false`、`T1=false`、`credit=0`。

## 未闭合的边界条件

- `admission_envelope_absent`：no future prepared-to-runtime admission envelope is present; the verifier has no request to authorize
- `prepared_rows_have_no_runtime_admission_receipt`：the 15 prepared row bindings declare required runtime products only as metadata; no runtime admission receipt is available
- `external_source_identity_attestation_absent`：Core manifest, known_inputs, solver binary, runtime identity, and per-cell source hashes have no independently trusted root attestation
- `runtime_observer_instance_unattested`：manufactured observer calibration is not a runtime observer instance binding and cannot authorize a worker
- `terminal_output_contract_not_closed`：result/audit/observations/trajectory terminal evidence is not present at this pre-run boundary; missing output must remain fail-closed
- `fresh_root_execution_authority_absent`：fresh root review and execution authorization are intentionally absent; caller JSON cannot mint either authority

此提交只建立可复用的 fail-closed contract checker。即使未来 envelope 形状完整，本组件也不会把 JSON 中的布尔声明当作 trusted root、runtime observer 或 execution authority；这些必须由独立外部 authority verifier 提供。

机器报告：`F1-PREPARED-RUNTIME-ADMISSION-BOUNDARY-V1-2026-09-29.json`。
