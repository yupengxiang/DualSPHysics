# F8 R008 synthetic diagnostic 的资格消费者首轮盘点

日期：2026-09-25（Asia/Shanghai）

范围：只读盘点 V5 草案要求的 formal admission、C-v1/per-case、T1 metric/reducer、gate registry 与最终 admission/release 边界。检索确认当前 `scripts/` 与 `tests/` 没有 `synthetic_non_qualifying`、`synthetic_only` 或 `diagnostic_outcome` 实现/测试；V5 仍只是报告草案。未修改消费者代码、资格数据或测试。

## 消费者与现状

| 边界 | 当前入口 | 本轮观察 | 相关测试/负向测试缺口 |
|---|---|---|---|
| Core manifest admission | `scripts/core_formal_admission_audit.py::_validate_manifest` / `audit_admission` | manifest schema 限于 `core.dataset.v1/v2`。但通用 `evidence` 输入由 `_evidence_rows` 将整个对象作为 global row；T1 聚合读取其 family/scope/`T1_numerical`，没有在读取 gate 字段前统一拒绝 synthetic schema/mode/evidence class。现有 V5 精确 Diagnostic 不含 family/T1 字段，故本观察不表示该精确对象可直接取得资格。 | `tests/test_core_formal_admission_audit.py` 覆盖 manifest、adapter 与分母；未找到 synthetic-marker/unknown-schema 的 global-evidence 拒绝测试。 |
| Core readiness | `scripts/core_formal_readiness.py::_admission_observation` / `build_readiness` | 文件声明 `ADMISSION_SCHEMA`，但该 helper 仅复制 schema 并抽取 `family_summary`、formal 状态等字段，没有校验 schema、mode 或 evidence class。非变更式调用探针传入 synthetic schema 标记及额外伪造字段后，helper 返回 3 个 T1 family、12 个 validation case。额外字段违反 V5 exact-output shape；结果只证明此字段抽取边界没有 schema gate，不证明最终 readiness/release 能被绕过。 | `tests/test_core_formal_readiness.py` 有正常 schema fixture 与 denominator 测试；未找到错 schema/synthetic class 必须在解析 gate 字段前被拒绝的用例。此处是首要 remediation/test target。 |
| 最终 release candidate | `scripts/core_formal_release_candidate.py::_validate_admission_observation` / `build_candidate` | 对 admission receipt 精确要求 `core.formal_admission_audit.v1`、status、formal 标志、固定 job 分母及 blockers；验证失败转成 blocked observation。`build_candidate` 当前自己调用 admission audit，而非接受任意外部诊断作为正式 receipt。 | `tests/test_core_formal_release_candidate.py` 覆盖 closure/completion 阻断与通过路径；尚无 synthetic schema 明确拒绝回归。 |
| F8 C-v1/per-case B→C→D provenance | `scripts/f8_r008_per_case_bundle_verifier_v1.py::verify_stage_bundle` / `verify_provenance_chain` | 限定 B/C/D stage、精确目录/字段、trusted authorization envelope 与逐 stage receipt schema；合成 diagnostic 不是 stage receipt。此处仍不弥补此前已记录的 C `solver_execution` 语义验证缺口，也不证明调用方 trust authentic。 | `tests/test_f8_r008_per_case_bundle_verifier_v1.py` 覆盖 stage/schema/provenance 和 synthetic stage fixtures；没有显式把 V5 Diagnostic 注入各 stage 并断言拒绝的用例。 |
| F8 T1 metric matrix | `scripts/f8_r008_t1_metric_matrix_adapter_v2.py::evaluate_metric_matrix_v2` | 只收恰好冻结的 15 个 per-case v2 验证结果，检查 result schema/bindings；输出明示 `full_t1_decision=false`、`readiness_pass=false`、`qualification_credit=0`。 | `tests/test_f8_r008_t1_metric_matrix_adapter_v2.py` 覆盖矩阵、case 分母与错误输入；缺显式 synthetic schema/mode/evidence-class 拒绝用例。 |
| F8 native-fluid reducer | `scripts/f8_r008_native_fluid_gate_reducer_v1.py::evaluate_native_fluid_window_gates_fd` | 只评 3 个 fluid/window 子门；要求已验证 table 语义与固定 case，输出仍是 partial、`T1_numerical=false`、zero credit。输入验证对象没有 synthetic-class 专门 guard。 | `tests/test_f8_r008_native_fluid_gate_reducer_v1.py` 覆盖表/时间窗/数值失败；缺 synthetic-class 负例。 |
| F8 fixed gate registry | `scripts/f8_r008_native_integrity_registry_v1.py::aggregate_native_integrity_statuses` | 只接收 15×8 固定行；case/gate/cell exact-field 与 state allowlist 检查会拒绝把完整 V5 Diagnostic 当作 case row；聚合输出自身明示不是 evidence verification、`T1_numerical=false`、zero credit。它接收的是裸 status cells，不能单独验证这些 cells 的来源类型。 | `tests/test_f8_r008_native_integrity_registry_v1.py` 覆盖 exact fields、状态和冻结分母；缺 V5 Diagnostic 及伪装 status-row 的来源隔离测试。 |

## 结论与安全边界

1. `core_formal_readiness` 是当前已确认的 schema-gating 缺口：在读取 `family_summary` 前缺少对 `ADMISSION_SCHEMA` 的拒绝校验；未使用的常量提示这不是计划中的行为。Core generic evidence admission 也没有统一的 synthetic marker 拒绝层。
2. F8 per-case/matrix/reducer/registry 各有不同精确结构边界，不能因其中一个 exact-field check 就推断整条链已拒绝 synthetic evidence。后续测试需分别注入 V5 exact object、带 synthetic marker 的 gate-shaped wrapper、缺 schema/unknown schema，并断言在解析/聚合 gate 值前 fail closed。
3. 这只是计划所列消费者的首轮代码入口盘点，不宣称整个仓库每个 diagnostic/qualification helper 均已穷尽。仍不得把 V5 Diagnostic 写成 receipt、包装后输入任一资格边界或作为 aggregate 子证据。
4. V5 设计未获有效 Terra High 审查，故本轮不改消费者实现、不新增这些测试，也不实现 harness；先保存边界发现。无 solver/worker/GPU/queue 或 production evidence 操作。
