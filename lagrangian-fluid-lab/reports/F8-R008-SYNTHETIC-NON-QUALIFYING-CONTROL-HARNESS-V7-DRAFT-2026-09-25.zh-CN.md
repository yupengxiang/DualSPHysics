# F8 R008 synthetic non-qualifying control harness v7（草案）

状态：V7 合并 V6 的未认证技术审查 `REVISE`。V6 reviewer 提供了技术意见但无可独立验证的 model/effort attestation；不记为 Terra High review/PASS。V4–V6 保留为历史稿。V7 仍未实现/测试，且不授权/启动 solver、native decoder、GenCase、worker、GPU/queue。

V7 采用两阶段时序：实现前只要求设计审查、封闭消费者清单和已批准测试计划；parser/consumer 机器测试只能在实现后运行，且须在任何 Diagnostic 输出被消费、持久化或接入 production gate 之前全部通过。审查/模型身份记录为独立流程元数据，不能代替机器安全 gate。

## 1. 唯一职责和绝对隔离

函数只解析调用者交给它的 synthetic UTF-8 JSON bytes，验证 exact shape，并比较两个彼此独立、不透明的 token。成功只说明字符串相等，不说明来源、原像、上下文、签名、scope、row、运行或文件真实。

输入/输出恒有 `mode="synthetic_only"`、`evidence_class="synthetic_non_qualifying"`；Diagnostic 不是 receipt，禁止写盘、重封装为 evidence、传入 registry 或作资格聚合子证据。无 `gate_state`；资格/执行授权恒为 false、credit 恒为 0、transition 恒为 none、registry write 和外部 I/O 恒为 false。匹配与否不得改变这些常量。

## 2. Production ingress 必须满足的可执行谓词

任何 qualification/admission/per-case/T1/reducer/registry/finalizer consumer 只有在以下验证成功后才能读 gate 字段：

```text
accept(raw_bytes, declared_schema, verifier_id, verifier_version,
       expected_scope, expected_source_bindings)
  := exact_allowlist(declared_schema, verifier_id, verifier_version)
     AND strict_decode(raw_bytes, reject_duplicate_keys=true,
                       normalize_keys=false)
     AND decoded_schema == declared_schema
     AND verifier(decoded_bytes, expected_scope, expected_source_bindings)
     AND provenance_hashes_match
  -> verifier-produced restricted VerifiedRecord
```

Consumer gate 不接受裸 `Mapping`、调用者声明为 Verified 的对象、JSON 重序列化副本、wrapper、缓存值或只复制字段的对象；跨进程/持久化后重入必须重新验证原始 bytes。V7 diagnostic 与所有由它复制、改字段、重命名 schema、重序列化、包装/派生的对象永远不属于任何 production allowlist。若现有 consumer 不能证明上述谓词，应 fail-closed 且不可作为资格证据 consumer；仅查 `mode/evidence_class` 标签不足以建立信任。

旧 production schema 若没有 `mode`/`evidence_class`，依 schema 的 exact fields 验证，不要求无关字段；若 schema 定义这些 discriminator，则缺失/未知/synthetic 值拒绝。未知或缺失 schema 一律在读取 score/credit/status/gate 前拒绝。

## 3. API 与 Diagnostic runtime type

唯一纯内存入口：

```text
diagnose_non_qualifying_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_token: str,
    expected_qualification_row_token: str,
) -> dict
```

静态 import allowlist 仅 `json`；不作 filesystem/FD/environment/network/log/callback/plugin/dynamic import/C-v1/registry/qualification I/O；无模块级可变结果、缓存或 service locator。

调用方每次调用前清空 result slot。validator 只接受 `type(value) is dict`；一次性 `snapshot=value.copy()` 后，只在 snapshot 上校验完整 exact key set、每个 key 为精确 `str`、所有值的精确 builtin type/常量/code-boolean 关系。拒绝所有 Mapping/dict 子类、额外/缺失字段和非精确原语类型。Python dict 本身不能表示重复 key；重复 key 仅由 input raw-bytes parser 拒绝。validator 不把该 mapping 或 snapshot 传入任何 gate，只能在 synthetic-only diagnostic path 读取非授权诊断码。

仅本次调用正常返回且唯一的 `validate_exact_v7_diagnostic` 成功，才可读取诊断。异常、超时、取消、进程退出、缺失/截断/无法解析返回、旧缓存值或 validator 失败，result slot 保持空并统一拒绝；不得默认补 open 或沿用上次结果。未预先分类的普通 `Exception` 映射为固定 `internal_error`，不外带异常文本/路径/环境；`MemoryError`、`KeyboardInterrupt`、`SystemExit`、`GeneratorExit`、进程/宿主崩溃不承诺返回，caller 仍 fail-closed。

## 4. Input schema 与唯一解析顺序

完整 UTF-8 严格解码之后，depth scanner 逐 Unicode code point 扫描。先命中的阶段唯一决定 diagnostic code：

1. `raw_json_utf8` 必须为精确 bytes，两个 expected token 必须为精确 str 且 ASCII/full-string `[0-9a-f]{64}`；否则 `invalid_arguments`。
2. 原始 bytes `>4096` 为 `too_large`（BOM 计长）；否则 BOM 或非法 UTF-8 为 `bad_encoding`。
3. lexical scanner 状态仅 `NORMAL/STRING/ESCAPE`，depth=0。NORMAL 中 `{`/`[` depth+1、刚到3返回 `too_deep`；`]`/`}` 在 depth>0 时 depth-1，在0时保持0。忽略括号类型配对和 JSON grammar，EOF 非零 depth 留给 parser。STRING 中反斜线进 ESCAPE、未转义 `"` 回 NORMAL；ESCAPE 消耗一 code point 回 STRING。
4. 固定 parser 调用：`json.loads(text, strict=True, object_pairs_hook=ObjectPairs, parse_constant=reject_nonstandard_constant, parse_int=JsonNumber, parse_float=JsonNumber)`。仅 `JSONDecodeError` 和专用 `NonstandardConstantError` 映射 `bad_json`；`ObjectPairs`、number marker 或其他 hook 的 unexpected exception 映射 `internal_error`。NaN/Infinity/-Infinity 不进入 shape。
5. 每个 JSON object 用有序私有 `ObjectPairs` wrapper，数组保持 list。完整 parse 后递归检测任一重复 key，映射 `duplicate_key`；确认全树无重复后才转普通 dict/list。意外遍历异常为 `internal_error`。
6. 在去重后的树上按下表验证 input exact fields/type/value；不符为 `bad_shape`；unexpected validator exception 为 `internal_error`。shape 有效后才比较两个 binding tokens。

冲突优先级因此为：invalid arguments > too large > bad encoding > too deep > bad JSON > duplicate key > bad shape > token mismatch/match。Parse 不完整时不检查 duplicate；scanner 不另加 grammar verdict。

| 字段 | 类型/值 |
|---|---|
| outer | JSON object；exact keys `schema,payload` |
| outer `schema` | exact str `core.cfd.f8.r008.synthetic_non_qualifying_probe.v7` |
| outer `payload` | JSON object；exact keys `schema,mode,evidence_class,probe_id,scope_token,qualification_row_token` |
| payload `schema` | exact str `core.cfd.f8.r008.synthetic_non_qualifying_payload.v7` |
| payload `mode` | exact str `synthetic_only` |
| payload `evidence_class` | exact str `synthetic_non_qualifying` |
| payload `probe_id` | exact str, full match `[a-z0-9][a-z0-9._-]{0,63}` |
| payload tokens | exact str, ASCII full match `[0-9a-f]{64}` each |

合法 schema 不含数字字段；`parse_int`/`parse_float` 返回保留 token text 的私有 `JsonNumber` 而不转换，任何 number 都于 shape 阶段成为 `bad_shape`，避免大整数转换和浮点 infinity。禁止 prefix match、Unicode normalization、大小写转换或自动 hash。上表示每字段规范，不以 JSON example 代替。

## 5. Diagnostic exact output

`validate_exact_v7_diagnostic` 校验完整字段集，拒绝额外/缺失字段。`type(value) is dict`、key 精确 str；string 值精确 str，布尔字段精确 bool，`qualification_credit` 精确 int 0（bool 不可冒充）。恒定字段：schema=`core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v7`、mode=`synthetic_only`、evidence_class=`synthetic_non_qualifying`、outcome=`non_qualifying`、eligibility/qualification/execution auth=`false`、credit=0、transition=`none`、registry_write=false、harness_performed_external_io=false。仅以下 code 和布尔组合允许：

| code | `payload_shape_valid` | scope match | row match | 条件 |
|---|---:|---:|---:|---|
| `invalid_arguments`,`too_large`,`bad_encoding`,`too_deep`,`bad_json`,`duplicate_key`,`bad_shape`,`internal_error` | false | false | false | 对应输入/异常阶段首个错误 |
| `scope_mismatch` | true | false | true | 仅 scope 不等 |
| `qualification_row_mismatch` | true | true | false | 仅 row 不等 |
| `scope_and_row_mismatch` | true | false | false | 两者不等 |
| `synthetic_bindings_match` | true | true | true | 两个不透明 token 分别相等 |

所有其他字段每行严格保持上述常量；诊断匹配永不表示资格通过。

## 6. Consumer 四元组清单与 fail-closed gate

每个 consumer 必须登记不可为空的四元组 `consumer_id → exact accepted schema versions → required verifier/version → negative-corpus pytest node IDs`，并另记录测试实际执行状态。任一 schema/verifier/node 缺失、node 不存在/未执行/失败或新增 consumer 未登记，consumer release gate 为 FAIL；不允许用“字段看似 exact”代替 source verifier。

| consumer_id | exact schema/当前限制 | required verifier/version | 必需负向测试节点（当前计划；缺失即 FAIL） |
|---|---|---|---|
| Core global evidence admission | 现有 F3/F4 T1 receipts 使用 `core.qualification.v1`；只能把它作为 exact schema 候选，其他 global evidence schema 必须另行登记 | `core-qualification-evidence@v1` strict/source-bound verifier（当前未实现；generic evidence path 缺此 verifier，blocked） | `test_core_formal_admission_audit.py::test_synthetic_evidence_rejected_before_global_t1_extraction` |
| Core readiness admission input | `core.formal_admission_audit.v1` | 已 source/hash 绑定的该 schema verifier；须在 `_admission_observation` 前运行 | `test_core_formal_readiness.py::test_unknown_or_synthetic_admission_schema_rejected_before_gate_parse` |
| Core release candidate | `core.formal_admission_audit.v1` | `core_formal_release_candidate.py::_validate_admission_observation` 的固定 source version + admission producer verifier | `test_core_formal_release_candidate.py::test_synthetic_admission_receipt_cannot_release` |
| F8 B/C/D per-case chain | B=`core.cfd.f8.r008_materialization_receipt.v1`; C=`core.cfd.f8.r008_solver_attempt_receipt.v1`; D=`core.cfd.f8.r008_decode_table_provenance.v1` | `f8_r008_per_case_bundle_verifier_v1.verify_stage_bundle/verify_provenance_chain@v1`，且各 stage source hashes 固定 | `test_f8_r008_per_case_bundle_verifier_v1.py::test_synthetic_diagnostic_rejected_for_every_stage` |
| F8 T1 metric matrix input | `core.cfd.f8.r008_native_fluid_table_metric_bundle_verifier.v2` | `f8_r008_native_fluid_table_metric_bundle_verifier_v2` + `f8_r008_t1_metric_matrix_adapter_v2@v2` | `test_f8_r008_t1_metric_matrix_adapter_v2.py::test_synthetic_or_rewrapped_result_rejected_before_metric_parse` |
| F8 fluid reducer input | outer verification=`core.cfd.f8.r008_native_fluid_table_semantics.v1`; embedded table=`core.cfd.f8.r008_native_fluid_frame_table.v2` | `f8_r008_native_fluid_table_v2` + `f8_r008_native_fluid_gate_reducer_v1@v1` | `test_f8_r008_native_fluid_gate_reducer_v1.py::test_synthetic_verification_mapping_rejected_before_reduction` |
| F8 gate registry | bare row currently exact `{case_id,gate_results}`; not a source schema, therefore raw production ingress is blocked pending verifier binding | source-bound per-case gate verifier before `aggregate_native_integrity_statuses@v1` | `test_f8_r008_native_integrity_registry_v1.py::test_synthetic_or_unbound_gate_rows_rejected_before_aggregation` |

上表为已发现 direct consumers 的最低集合，不宣称仓库其他资格/diagnostic helper 已穷尽。实现前须完成全仓 consumer sweep，扩充完整四元组；目前所有新增负向 node 尚未实现，Core readiness/admission schema guard 缺口已在[首轮盘点](F8-R008-SYNTHETIC-CONSUMER-INVENTORY-2026-09-25.zh-CN.md)确认，故本 gate 当前 FAIL。

## 7. 分阶段实现与测试门

**实现前 gate**：V7 技术设计审查通过；consumer sweep 完整；上表每行的 schema allowlist/verifier version/negative-test plan 已评审固定。通过仅允许纯内存 parser 与 synthetic-only tests 的实现。

**实现后、任何输出使用/接入前 gate**：运行并通过所有 diagnostic code/输出逐字段类型常量断言；priority-conflict table（size+encoding、depth+syntax、duplicate+shape、nonstandard constant+shape、escape/quote/container）；scanner 状态/EOF/size/BOM/UTF8；duplicate nesting/object-array 区分；调用端 stale result slot/timeout/missing-output；以及上表每个 consumer 的 V7 exact object、重名 duplicate discriminator、unknown/missing schema、production-schema 重标、gate-shaped wrapper、copy/re-serialize 缓存对象负向 corpus。记录不可为空的 pytest node IDs、实际执行结果与 consumer 清单 hash；任一失败或漏项都保持 FAIL。

另须证明所有生产 bytes ingress 使用 reject-duplicate/no-normalization parser、verified record 不能由任意 Mapping 构造、来源 bytes/hash/schema/verifier/version 在跨边界重验。若当前系统不能证明，就不得接受该证据，也不得把 harness Diagnostic 用于资格路径。

实现前和实现后两道 gate 严格分开；任何设计 PASS、单测通过或 Diagnostic `synthetic_bindings_match` 都不等于 C-v1、native integrity、T1、readiness 或资格信用。R008 execution gate 仍 `open`、`T1_numerical=false`、零信用；本草案不接线、不修改冻结输入、不授权运行 solver/worker/GPU/queue。
