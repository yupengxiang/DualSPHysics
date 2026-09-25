# F8 R008 per-case B/C/D bundle verifier v2 remediation（草案）

状态：首轮只读交叉设计复核为 `REVISE`；本版补入 exact per-attempt/15-case aggregate、受信完整 ledger、stage/ref/root/nonce 与 seq 偏序。focused follow-up 确认最后一轮 ledger identity/terminal/order 修订在文本层面闭合。仍未实现、未运行测试；保留 v1 源码、receipt 和历史结果不变，不读取或改写生产 bundle/solver frame，不运行 B/C/D、native、GenCase、solver、worker、GPU 或 queue。

nonce 格式补充：本 synthetic V2 attempt `nonce_hex` 与 C V5 `attempt_nonce_hex` 统一为 32 位小写 hex（128-bit）；这里只冻结字符串编码长度，不证明随机来源、attempt 唯一性或 supervisor trust。

## 1. 消费者分层

v1 `verify_stage_bundle()` / `verify_provenance_chain()` 保留为 structural receipt/output-tree/reference verifier。其 `all_stages_passed` 只能解释为“B/C/D receipt 的 status 字段均为 `passed`”，**不能**解释为 GenCase、solver execution、native decode、HDF5/table 内容或资格语义均已验证。该旧字段禁止作为新 qualification consumer 的唯一通过条件。

已存在的上层校验必须被显式复用而非重复编写：`f8_r008_native_fluid_table_bundle_verifier_v1.py` 与 `f8_r008_native_fluid_table_metric_bundle_verifier_v2.py` 会在持有的 table FD 上调用 `verify_native_fluid_table_fd()`，重算表 schema/axes/逐帧内容并与 C 原始 BI4 frames 对照；上层路径也独立重验 B Definition/control source binding。此表语义补偿不能认证 C 的进程执行真实性或 B 的 GenCase 执行真实性，也不能消除 caller-trust/runtime identity 前提。

每个新 attempt result 使用固定 schema `core.cfd.f8.r008_per_case_attempt_verification.v2`，exact keys 为：

```text
{schema,scope_id,case_id,qualification_row_sha256,attempt_id,nonce_hex,
 attempt_ledger_registration_seq,attempt_ledger_event_seqs,stage_bundle_refs,stage_receipt_statuses,
 definition_control_raw_bindings_verified,materialization_binary_semantics_verified,
 gencase_execution_semantics_verified,solver_execution_semantics_verified,
 native_table_content_matches_C_raw_frames,loaded_module_code_identity_verified,
 attempt_outcome,expected_frame_count,actual_frame_ordinals,
 actual_time_axis_ieee754_hex,failure_class,failure_position,
 qualification_adjudicated,T1_numerical,qualification_credit
}
```

`stage_receipt_statuses` exact object keys `{B,C,D}`；values 仅 `{not_run,passed,failed,incomplete,timeout,oom,signaled}`。`stage_bundle_refs` 是 exact `{B,C,D}` object；每值为 null 或对应固定 stage/role 的 V4 descriptor-ref exact shape `{stage,role,object_id,bytes,sha256}`。非 null 引用解出的 receipt 必须逐字段匹配同一 `scope_id,case_id,qualification_row_sha256,attempt_id,nonce_hex`；尤其 C receipt 内 V5 journal/evidence 的 `attempt_nonce_hex` 必须与 attempt `nonce_hex` 相等，禁止跨 attempt 或跨 stage 拼接。缺产物时 ref 可为 null，但 ledger 必须解释对应阶段为何未启动/未产出，且永不得通过资格门。`attempt_ledger_registration_seq` 是该 scope append-only ledger 内唯一 `attempt_registered` event 的 seq；`attempt_ledger_event_seqs` 是该 attempt 在 scope ledger 中全部相关 event seq 的严格递增、无重复整数数组，必须包含 registration、所有 stage/process terminal events 及（若已结束）attempt terminal event，且与 ledger 逐项相等。`attempt_id` 必须是固定 ASCII ID grammar，`nonce_hex` 是固定长度小写 hex；两者唯一绑定该 row 的 trusted ledger attempt。seq/bytes/count 均为 builtin integer 且 bool 不算 integer；所有 boolean 为 builtin bool；所有 digest 为 64 位小写 hex。`attempt_outcome` enum 固定 `{not_started,passed,failed,incomplete,timeout,oom,signaled,unresolved}`，由已验证对象与规则派生，caller 不可自报。无修饰旧字段 `all_stages_passed` 禁止出现在 v2 output。

`expected_frame_count` 从冻结资格 row 的 axis 派生；`actual_frame_ordinals` 必须是 `0..k-1` 精确连续前缀，`actual_time_axis_ieee754_hex` 必须逐位等于冻结 axis 同一前缀，`0 <= k <= expected_frame_count`。`passed` 仅在 B/C/D statuses 全部 passed、完整 axis 恰好匹配、对应 GenCase/C execution 及 loaded-module identity contract 都已 independently verified、所有 required booleans 为 true 时允许；当前这些 trust/parser 前提不存在，因此当前实现的 `attempt_outcome=passed` 一律禁止。失败 attempt 必须保留可证明的失败类别与位置：`failure_class` enum `{execution_error,incomplete_output,timeout,oom,signal,resource_limit,unresolved_evidence}`；有可定位帧进度时 `failure_position` 为下一个未完成的零基 frame ordinal（`0..expected_frame_count`），无可信帧进度时仅 `unresolved` 可为 null。`passed` 与 `not_started` 的 `failure_class`/`failure_position` 必须为 null；not_started 时 frame arrays 为空且 status 全为 not_run。

`attempt_outcome` 只能由以下规则唯一派生：`not_started` 要求 supervisor ledger 明示未 spawn 且三阶段全为 `not_run`；`timeout|oom|signaled` 必须有相应 trusted resource/process terminal event 且 `failure_class` 分别为 `timeout|oom|signal`；`incomplete` 用于有实际 spawn 但没有通过且产物/terminal event 不完整的情形；`failed` 要求有可信 terminal failure；`unresolved` 表示缺失/不可信的来源或契约，不能当作一次数值失败或 PASS。terminal status 与 `failure_class` 必须一致；B→C→D 必须遵循冻结执行顺序，下游 stage 不得在上游未 `passed` 时启动，每个非 `not_run` status 都须由相应 stage receipt 或 trusted terminal event 支持；互相矛盾的 stage status/outcome 组合一律 unresolved。所有 raw attempt/receipt/outcome 由 ledger 按 append-only seq 保留，不允许 caller 覆写。

在可信 GenCase execution contract、V5 C execution journal parser、trusted supervisor/runtime attestation 和正式资格矩阵 producer 全部存在前，`gencase_execution_semantics_verified=false`、`solver_execution_semantics_verified=false`、`loaded_module_code_identity_verified=false`、`qualification_adjudicated=false`、`T1_numerical=false`、`qualification_credit=0` 都是固定值。结构 PASS 与 table-content PASS 仍可作为 diagnostic 子结果，不得提升 case 或 scope qualification。

attempt-result 的资格语义布尔集合固定且不得省略：`definition_control_raw_bindings_verified`、`materialization_binary_semantics_verified`、`gencase_execution_semantics_verified`、`solver_execution_semantics_verified`、`native_table_content_matches_C_raw_frames`、`loaded_module_code_identity_verified`。Future PASS 需要这六项全部为 builtin `true`，同时有 B/C/D 三个非 null stage bundle refs 与 ledger 对应 stage receipt events 一一相等；caller 自报 true、缺 ref 或缺 producer contract 均不能通过。当前 synthetic verifier 仍按上一段将 execution/identity/qualification booleans 固定 false。

## 2. B/C 语义与失败分母

- B 必须通过 descriptor-root reader 绑定冻结 Definition、control 和相应 case inputs；按 exact schema 校验 `gencase_execution`，确认执行 argv/runtime/output namespace 与 authorization envelope 一致；`safe_decode_receipt` 不能是空对象，必须重算其 input BI4 raw bytes、完整数组/身份元数据与 output manifest。若没有可信 GenCase event source，只能报告 `gencase_execution_semantics_verified=false`，不得接受 B `status="passed"` 作为资格输入。
- C 必须按 C-execution V5 以一条 attempt 统一 event journal 绑定 invocation、solver root/process-generation、query 调用图、termination 和 resources。V5 parser 缺失、journal overflow/loss、`solver_execution`/`execution_controls` 为空或仅含 caller boolean 时，只能保留 execution unresolved/failure outcome，不得得到 `solver_execution_semantics_verified=true`。
- 失败或不完整 C attempt 可拥有少于预期的实际帧，但其 attempt result 必须保留 actual frame prefix 与失败位置；只能阻止 B→C→D qualifying-success 闭环，不可从 15-case 分母或失败统计中删除。对 `passed` attempt 仍须精确匹配完整预登记时间轴。C 的 `poll_begin` 无 terminal `poll_end`、exception end 或 signal/timeout 均须留在 attempt record 并非通过。
- D table 内容继续由已有 FD-based上层 verifier 重算；v2 aggregate 必须把 result 身份与 held-FD table/source manifest 完全绑定，不能把仅 v1 `table path + byte/hash` 结果命名为 content verification。

ledger 固定 schema `core.cfd.f8.r008_attempt_ledger.v1`，descriptor-root exact ref 与 scope aggregate 一同保存；其 exact top-level keys 为 `{schema,scope_id,qualification_matrix_raw_sha256,supervisor_source_id,coverage_start_ns_hex,coverage_end_ns_hex,event_count,overflow,lost_count,events}`。event 顶层使用连续全局 seq `0..event_count-1`、非递减 monotonic time；`overflow=false`、`lost_count=0`，coverage 必须由 scope admission 前覆盖至 supervisor 明确关闭该 scope 后，并包括所有 attempt registration/spawn/terminal 边界。事件 common keys 为 `{seq,mono_ns_hex,kind,case_id,qualification_row_sha256,attempt_id,nonce_hex}`；kind branches 为 `attempt_registered`（仅 common keys）、`attempt_spawn`（另加 `stage,process_generation_id`）、`stage_receipt`（另加 `stage,receipt_ref`）、`process_terminal`（另加 `stage,process_generation_id,process_journal_ref`）、`attempt_terminal`（另加 `outcome,terminal_ref`）。每个 attempt 必须恰有一个 registration；每个实际启动的 stage 最多一个 invocation-root `attempt_spawn`，B/C 若启动必须恰有一个，D 的数量由固定 D execution contract 声明其为 in-process 或 process-backed；同一 stage 内额外 child generations 只在对应 stage process journal 中记录，不得伪装成新 invocation root。stage receipt 只允许 B→C→D 顺序；未 spawn 只能由无任何 stage `attempt_spawn` 且 `attempt_terminal.outcome="not_started"` 表示；spawn 后缺 terminal 只能是 incomplete/unresolved；重复 ID/nonce、无注册 event 的 stage/process event、跳号/漏报/coverage 缺口或无法关联的 event 均令 ledger 不完整。scope aggregate 的 `attempt_ledger_ref` 与 `attempt_ledger_attestation_ref` 均为固定 stage/role registry target 的 exact descriptor-ref `{stage,role,object_id,bytes,sha256}`；`attempt_ledger_raw_sha256` 必须等于 ledger ref 的 raw SHA。只有 descriptor-root reader 验证 raw ledger 与 exact schema，且 `VerifiedAttemptLedgerV1` capability 验证可信 supervisor attestation 对 `(scope,matrix_raw_sha256,ledger_raw_sha256,supervisor_source_id,coverage bounds,event_count,overflow,lost_count)` 的完整性背书时，才能派生 `attempt_ledger_complete=true`。该 capability/attestation trust activation 尚未实现；缺失时 ledger completeness=false，所有无记录 row 为 `unresolved` 而非 `missing`，且 aggregate 不得有资格通过路径。

`event_count`/`seq` 必须为 builtin nonnegative JSON integer（bool 不算 integer），`mono_ns_hex`、coverage endpoints 均为 16 位小写 hex monotonic nanoseconds，start≤end 且所有 event 落在闭区间内；scope/case/attempt/source IDs 遵循 fixed ASCII grammar，nonce 与 V5 `attempt_nonce_hex` grammar 相同，所有 row/matrix/ledger digest 均为 64 位小写 hex。`stage_receipt` 的 stage 仅 `{B,C,D}`，receipt ref 为该 stage 固定 role 的 V4 descriptor-ref；`attempt_terminal.outcome` enum 固定 `{not_started,passed,failed,incomplete,timeout,oom,signaled,unresolved}`，`terminal_ref` 对 `not_started` 必须 null，对其他 outcome 必须是受信终态 descriptor-ref；任何 caller 填写的 outcome 都从对应事件/receipt重算。`attempt_spawn` 与每个 stage/process terminal 必须能按同一 attempt ID/nonce 闭合。`process_terminal` 是上述 event union 的另一 exact branch：common keys 加 `{stage,process_generation_id,process_journal_ref}`，`stage` 仅 `{B,C,D}`；其 generation 与对应 stage execution journal 的 root/terminal generation 完全相同，`process_journal_ref` 必须指向该 attempt 的 stage bundle 中实际终态证据。每个 process-backed B/C/D stage 的 process terminal 都须在完整 ledger 中出现，且所有 stage bundle refs 必须逐字节等于对应 `stage_receipt.receipt_ref`；attempt result 的 `attempt_ledger_registration_seq`、`attempt_ledger_event_seqs` 必须精确列出所有且仅有该 attempt ID/nonce 的 ledger events，不能漏掉终态或重试事件。aggregate 中 ledger ref 固定 `(stage="runtime",role="attempt_ledger")`，attestation ref 固定 `(stage="runtime",role="attempt_ledger_attestation")`，两者均须命中固定 registry schema，caller 不可自选 target。

每个 attempt event 顺序必须为唯一 `attempt_registered` 在先、该 stage 的 `attempt_spawn` 在 stage 内容产生前、B→C→D 的 stage transitions 严格递增、全部对应 process terminal 在 attempt terminal 前；每 attempt 最多且在完整 ledger 中恰有一个 `attempt_terminal`，之后不得再有该 attempt 的 event。每个 spawned process generation 恰有一个 `process_terminal`，终态 event 须与其 stage journal 中的 exit/signal/reap 记录逐项相等；缺终态、重复 root、重复 terminal 或顺序倒置都令该 attempt unresolved/incomplete，且不能判为 ledger-complete success。

具体 seq 偏序固定为：process-backed stage 的 `attempt_spawn.seq <` 该 stage 每个 process generation 的 `process_terminal.seq < stage_receipt.seq`；B 的 stage receipt 必须早于任一 C `attempt_spawn`，C 的 stage receipt 必须早于任一 D `attempt_spawn`。in-process stage 无 spawn/process-terminal 事件，但仍须按 B→C→D 的 stage receipt 顺序记录；上游 stage 非 `passed` 时不得出现下游 spawn 或 stage receipt。没有成功 stage receipt 的失败路径以可信 terminal/status event 结束，随后不得进入下游 stage。任何相等/逆序 seq、缺少应有中间事件或多余下游 event 均使 aggregate unresolved/nonpassing。

所有 `receipt_ref`、`process_journal_ref` 和非 null `terminal_ref` 均使用 V4 descriptor-ref exact shape `{stage,role,object_id,bytes,sha256}` 并命中固定 `(stage,role)` registry target；禁止额外字段或 caller-selected target。

`attempt_terminal.outcome` 必须逐字节等于对应 per-attempt result 的派生 `attempt_outcome`；stage receipt event、process terminal event、各 `stage_bundle_refs` 与 `attempt_ledger_event_seqs` 必须双向闭合，不允许只从 result 单向声称引用存在。`attempt_ledger_event_seqs` 必须显式包含每个 `attempt_spawn` seq。对 C，唯一 `attempt_spawn(stage="C").process_generation_id` 必须精确等于该 attempt C V5 payload 的 `invocation.process_generation_id`，并等于 V5 journal 唯一 root `spawn` event 的 generation；每个 V5 process terminal generation 必须有且仅有一个同 generation、同 attempt ID/nonce 的 ledger `process_terminal` 引用。B 及 process-backed D 使用其 versioned execution contract 中对应的 invocation/root generation 做相同逐字段相等检查；若该合同尚未定义或 generation 数量不符，该 stage semantics 为 false/unresolved。每个 attempt 每 stage 最多一个 invocation root；重试必须使用新的 attempt ID/nonce，不允许在同一 attempt 内悄然生成第二个 root。

completeness attestation 固定 schema `core.cfd.f8.r008_attempt_ledger_attestation.v1`，exact keys 为 `{schema,scope_id,qualification_matrix_raw_sha256,attempt_ledger_raw_sha256,supervisor_source_id,coverage_start_ns_hex,coverage_end_ns_hex,event_count,overflow,lost_count,signature_algorithm,verification_key_id,signature_base64}`；该 exact attestation object 按 V12 canonical JSON strict rules 编码；算法固定 `ed25519`，签名是 canonical standard-base64 64-byte Ed25519 signature。签名消息精确为 `ASCII("CORE-F8-R008-ATTEMPT-LEDGER-ATTESTATION-V1") || 0x0a || canonical_json(attestation_without_signature_base64)`；验证 key 必须由 out-of-band active/revocation registry 绑定可信 supervisor identity，不能由 ledger/attestation 自带 key 导入。scope、matrix/ledger raw SHA、source identity、coverage、event count 与 overflow/lost count 必须和 ledger/ref 逐字段相等。签名只能证明受信 supervisor 对“coverage 完整且无事件遗漏”的声明；root/runtime trust activation 与真实事件源仍未实现，不能用 synthetic attestation 升格。

scope aggregate 使用固定 schema `core.cfd.f8.r008_t1_case_attempt_aggregate.v2`，exact keys 为：

```text
{schema,scope_id,qualification_matrix_raw_sha256,attempt_ledger_ref,attempt_ledger_raw_sha256,
attempt_ledger_attestation_ref,
expected_case_count,case_rows,case_outcome_counts,attempt_outcome_counts,aggregate_outcome,
attempt_ledger_complete,qualification_adjudicated,T1_numerical,qualification_credit}
```

`qualification_matrix_raw_sha256`/`attempt_ledger_raw_sha256` 是 64 位小写 hex 并分别绑定 frozen matrix 与完整 ledger 原始 bytes；`expected_case_count` 为 builtin integer 且必须等于 matrix 的 15；`attempt_ledger_complete` 为 builtin bool。`case_rows` 必须依冻结 matrix 顺序逐一且仅一次覆盖全部 15 个 `case_id`，不能由 receipt directory listing 决定分母。每行 exact keys 为 `{case_id,qualification_row_sha256,case_outcome,qualifying_attempt_id,attempts}`；case/row IDs 与 row digest 必须与 matrix 对应行完全一致，`case_outcome` enum `{passed,failed,missing,unresolved}`，`qualifying_attempt_id` 为 null 或精确 attempt ID。`attempts` 按可信 append-only ledger seq 升序，逐条嵌入完整 exact attempt-result v2 object，保留所有 `not_started|passed|failed|incomplete|timeout|oom|signaled|unresolved` record；attempt ID/nonce 不得重复或被后续结果覆盖。若没有任何已 spawn attempt（列表为空，或只含由 ledger 证明未 spawn 的 `not_started` records），`case_outcome="missing"` 且 qualifying ID 为 null；这些 not_started records 仍保留并计入 attempt tally。否则，有通过 attempt 时 qualifying ID 必须是 ledger 顺序最早的通过 attempt；没有通过但有 unresolved 时 row=`unresolved`；其余已启动且结束、但均未通过时 row=`failed`。若 retry 后通过，先前失败仍在 attempts 并计入 attempt outcome tally。

`case_outcome_counts` exact keys `{passed,failed,missing,unresolved}`，`attempt_outcome_counts` exact keys `{not_started,passed,failed,incomplete,timeout,oom,signaled,unresolved}`；两者的 values 是 builtin nonnegative integer，均由 case rows/attempt records 重算，case counts 总和必须为 15，attempt counts 总和必须等于总 attempt 数。`attempt_ledger_complete=true` 仅当 trusted supervisor 提供该 scope append-only ledger 的完整 inventory，且 ledger 内所有已创建 attempt 与 aggregate 逐一对应；`aggregate_outcome` enum `{accounting_complete,accounting_unresolved}`，仅在完整 ledger + 15 行完整 + 所有引用重验通过时为 `accounting_complete`，否则为 `accounting_unresolved`。该字段只说明账目/来源完整，不代表任何 case 或 qualification 通过；15 行完整也不代表15次 solver 已运行。当前没有 trusted ledger、V5 parser/runtime identity 或正式矩阵 producer，故 aggregate 固定 `qualification_adjudicated=false`、`T1_numerical=false`、`qualification_credit=0`。

case/scope 正向及缺失派生谓词唯一如下：`case_outcome="passed"` 当且仅当至少一个 ledger-complete、所有 B/C/D receipt 与同 attempt ID/nonce 严格绑定且全部 required semantics booleans independently verified 的 attempt 为 `passed`，并且该 row 的所有其他 attempts 也均有可信、非 unresolved 的终态；qualifying ID 取 ledger 顺序最早的此类 attempt。`case_outcome="missing"` 仅能在可信完整 ledger 明确证明该冻结 row 没有任何 spawned attempt 时输出（可保留只含 `not_started` 的 registration）；ledger 不完整或 attestation 不可信时，不能由空目录/空列表推导 missing，受影响 row 必须 unresolved。`case_outcome="failed"` 要求 ledger complete、至少一个 spawned attempt、所有 attempts 均有可信 terminal outcome 且没有 unresolved 或 passed；其他情况为 unresolved。`T1_numerical=true` 的唯一未来门必须同时要求 trusted qualification adjudicator、complete ledger、15 个冻结 row 全部 `passed` 且各有唯一有效 qualifying attempt、无 missing/unresolved、各 row qualifying attempt 的 B/C/D/native/execution/identity gates 完整通过，并且完整 attempt history 按冻结 retry allowance 与失败分母重算后仍通过所有预登记 T1 metric/hard gates；任何计数或引用不闭合都固定 `T1_numerical=false`、`qualification_credit=0`。本草案/当前 synthetic verifier 仍强制 `qualification_adjudicated=false`、`T1_numerical=false`、`qualification_credit=0`，上述未来正向谓词不构成现有实现路径或执行授权。

上句“15 个 attempt 的 gates”指 15 个 frozen row 各自被选中的 qualifying attempt，不是把 retry 历史缩成 15 项；资格判定仍须输入整个 append-only attempt history。

失败分母与 retry policy 只按冻结资格合同解释：attempt counts 始终覆盖 append-only ledger 的全部已注册 attempts，任何后续成功均不得删除、覆盖、合并或重编号较早的 failed/timeout/OOM/signaled record；T1 正向谓词还必须对完整 attempt history 按冻结失败分母和 retry allowance 重新判定，不能只挑选每行的 `qualifying_attempt_id` 而忽略其余 attempt outcome。未被冻结 retry policy 明确允许的 retry 不得用来替代失败样本。

## 3. Synthetic-only 验收节点

以下均用内存/`tmp_path` 小型 BI4/HDF5，不加载固定生产 receipt、bundle、HDF5、solver frame 或 one-shot namespace：

- `test_f8_r008_per_case_bundle_verifier_v2.py::test_structural_all_stage_status_does_not_claim_execution_or_t1`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_empty_b_gencase_and_safe_decode_objects_cannot_set_materialization_verified`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_empty_c_execution_controls_cannot_set_solver_execution_verified`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_failed_partial_c_attempt_is_retained_but_never_passed`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_held_fd_table_content_pass_remains_separate_from_execution_semantics`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_aggregate_has_all_fifteen_rows_and_marks_unattempted_rows_missing`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_not_started_only_case_is_missing_but_attempt_history_is_retained`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_rejected_retry_pass_claim_does_not_erase_earlier_failed_attempt`
- `test_f8_r008_per_case_bundle_verifier_v2.py::test_poll_without_terminal_event_is_preserved_as_incomplete`

每个 public v2 entry 都需断言拒绝/降级发生在 qualification/T1 派生之前；任何 synthetic PASS 固定 `qualification_adjudicated=false`、T1 false 和零 credit。以上只定义可审查的软件语义，不替代 V5 producer、trusted launcher、15-case 实际证据或计划中的正式资格/资源准入。
