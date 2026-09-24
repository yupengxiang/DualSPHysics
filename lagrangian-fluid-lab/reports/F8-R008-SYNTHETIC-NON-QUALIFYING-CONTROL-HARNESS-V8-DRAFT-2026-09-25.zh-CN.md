# F8 R008 synthetic non-qualifying control harness v8（草案）

状态：V8 合并 V7 的未认证技术审查 `REVISE`。Reviewer 无可独立验证 model/effort attestation；只记录技术意见，不记 Terra High review/PASS。V4–V7 保留为历史稿。无 parser/consumer 代码或测试已实现；R008 资格 execution gate 仍 open、`T1_numerical=false`、零信用。本设计不授权或启动 native decoder、GenCase、solver、worker、GPU 或 queue。

## 1. 职责与输出/输入边界

函数只解析 synthetic UTF-8 JSON bytes，检查 exact input shape，比较两个彼此独立、不透明的 token。binding 相等只说明字符串相等，不证明来源、原像、上下文、签名、scope、row、运行或文件真实。

只有函数**正常返回的每个 Diagnostic** 才恒带 `mode="synthetic_only"`、`evidence_class="synthetic_non_qualifying"` 和本规范的其他固定输出常量；任意 raw input 本身不保证有这些字段。只有 parsed payload 通过 exact shape 检查后，才有输入侧 discriminator。Diagnostic 不是 receipt，禁止写盘、重封装为 production evidence、进入 registry 或作为资格聚合子证据；无 `gate_state`，资格/执行授权恒 false、credit 恒 0、transition 恒 none、registry write 与 harness 外部 I/O 恒 false。

唯一 API：

```text
diagnose_non_qualifying_synthetic_probe(
    raw_json_utf8: bytes,
    expected_scope_token: str,
    expected_qualification_row_token: str,
) -> dict
```

纯内存，不作 filesystem/FD/environment/network/log/callback/plugin/dynamic-import/C-v1/registry/qualification I/O；import allowlist 仅 `json`，无模块级可变结果、cache 或 service locator。

## 2. Production ingress 的 exact verifier 谓词

每个 production ingress 必须先以原始 bytes 验证，之后才能解析任何 score/credit/status/gate 字段。闭合 allowlist 是不可变精确三元组集合：

```text
ALLOWLIST = {(exact_schema_string, verifier_id_string, verifier_version_string), ...}
```

`accept` 的输入/步骤定义如下，`strict_decode` 返回 `decoded_value` 而非 bytes：

```text
accept(raw_bytes, declared_schema, verifier_id, verifier_version,
       expected_scope, expected_source_bindings):
  require type(raw_bytes) is bytes
  require type(declared_schema) is str
  require type(verifier_id) is str and type(verifier_version) is str
  require type(expected_scope) is str
  require type(expected_source_bindings) is tuple
  require (declared_schema, verifier_id, verifier_version) in ALLOWLIST
  decoded_value = strict_decode(raw_bytes, reject_duplicate_keys=True,
                                normalize_keys=False)
  require type(decoded_value) is dict
  require type(decoded_value.get("schema")) is str
  require decoded_value["schema"] == declared_schema
  require verifier(raw_bytes, decoded_value, expected_scope,
                   expected_source_bindings) == VALID
  return verifier_private_factory(raw_bytes, decoded_value, verifier tuple)
```

`expected_source_bindings` 的精确运行时形式为按 `role` 字符串升序、无重复的 tuple；每个元素为精确 tuple `(role: exact str, byte_count: exact int, sha256: exact lowercase 64-hex str)`。`bool` 不可作为 `byte_count`；byte_count 的正值/上限由 tuple 中 verifier version 对应的 schema-specific contract 固定，超界拒绝。`ALLOWLIST` 本身也是由受信 verifier 包固定的精确 tuple 集合，不能由调用者提供/扩展。Verifier 逐 role 从规定的根 descriptor-relative/no-follow 读取原始 bytes，检查 stat byte_count、raw-byte SHA-256、scope 与声明 role；任何未列 role、缺项、复项或 hash/size 不符即拒绝。

SHA-256 一律对输入/被引用对象的**原始 bytes** 计算：`sha256(payload_bytes).hexdigest()`，不先 JSON parse/serialize、不使用规范化 JSON 代替来源 bytes。每个 reference 的 schema-specific verifier 必须明确检查 role、byte count、SHA-256 和 expected scope；参考对象 bytes 由受信 descriptor-relative/no-follow 读取器取得。`expected_source_bindings` 是按精确 role 枚举的不可变期望表；缺项/多项/摘要不符拒绝。此处不声称各类历史 receipt 已满足该合同。

`VerifiedRecord` 是 verifier 模块私有的、仅内存、不可 JSON/pickle 序列化的 opaque capability，记录 raw-bytes SHA-256、schema、verifier ID/version 与已校验 provenance 摘要；内部构造须带该模块私有的 process-local identity seal，且构造器不导出。公开 consumer API 只接收原始 bytes 和 exact allowlist tuple，不接收 `Mapping`/裸 `VerifiedRecord`；同进程私有调用仅把 capability 交给固定 consumer。跨进程、持久化或重新进入一律从原始 bytes 重验，不信任 Python class、marker、wrapper 或缓存。若运行环境/加载模块本身不在信任闭包内，则该入口 fail-closed；仅靠 Python 私有名称不防同进程任意恶意代码。

每个 production ingress 的模式约定为：schema 必须存在且在 allowlist；只有该 exact schema 定义 `mode`/`evidence_class` 时才要求相应字段，并在精确检查中拒绝 missing/unknown/synthetic 值。没有这些字段的旧 schema 不得因无关字段而被破坏。任何 V8 Diagnostic、重标/复制字段或由其重新序列化/派生的对象均不在 allowlist。

## 3. Input exact schema 和解析顺序

首个命中阶段唯一决定 code，按以下顺序：

1. raw 参数必须为精确 `bytes`，两个 expected token 必须为精确 `str`、ASCII 且 whole-string 匹配 `[0-9a-f]{64}`；失败 `invalid_arguments`。
2. raw length `>4096` bytes 为 `too_large`（BOM 计入）。
3. 长度检查后、decode 前执行 `raw_json_utf8.startswith(b"\xef\xbb\xbf")`；命中为 `bad_encoding`。然后以 UTF-8 strict decode；仅 `UnicodeDecodeError` 映射 `bad_encoding`。
4. 对 decoded Unicode text 按 code point 做 bounded lexical depth scan。状态仅 `NORMAL/STRING/ESCAPE`，depth 初始 0。NORMAL 遇 `{`/`[` depth+1，刚到 3 即 `too_deep`；遇 `}`/`]` 在 depth>0 时 depth-1，否则保持0。扫描器不检查括号类型配对、不判 JSON grammar、EOF 非零 depth 留给 parser。STRING 中反斜线进 ESCAPE、未转义 `"` 回 NORMAL；ESCAPE 消耗下一 code point 后回 STRING。
5. parser 调用固定为 `json.loads(text, strict=True, object_pairs_hook=ObjectPairs, parse_constant=reject_nonstandard_constant, parse_int=JsonNumber, parse_float=JsonNumber)`。仅 `json.JSONDecodeError` 及仅由 `parse_constant` 抛出的专用 `NonstandardConstantError` 映射 `bad_json`。Unexpected decoder/parser/hook/JsonNumber exception 一律 `internal_error`；不可恢复 `MemoryError` 等例外见第 6 节。
6. `ObjectPairs` 为每个 object 产生私有有序 wrapper，JSON array 保持 list。完整 parse 后递归查 duplicate；已定义的 `DuplicateKeyDetected` 映射 `duplicate_key`，tree walk 的其他异常 `internal_error`。确认全树无重复后才转普通 dict/list。
7. 在去重树上按下表检查输入 exact shape/type/value，定义的 shape mismatch 为 `bad_shape`，unexpected validator exception 为 `internal_error`。只有 shape valid 后才比较 tokens。

同一阶段未分类异常均为 `internal_error`，不可自行归入 parser/shape 错误。阶段优先级为：参数 > 大小 > BOM/encoding > depth > JSON parse > duplicate > shape > binding。Parse 不完整不检查 duplicate。

| 输入字段 | 精确要求 |
|---|---|
| outer object | JSON object；恰为 `schema,payload`，无 duplicate key |
| outer `schema` | exact str `core.cfd.f8.r008.synthetic_non_qualifying_probe.v8` |
| outer `payload` | JSON object；恰为 `schema,mode,evidence_class,probe_id,scope_token,qualification_row_token` |
| payload `schema` | exact str `core.cfd.f8.r008.synthetic_non_qualifying_payload.v8` |
| payload `mode` | exact str `synthetic_only` |
| payload `evidence_class` | exact str `synthetic_non_qualifying` |
| payload `probe_id` | exact str, whole-string `[a-z0-9][a-z0-9._-]{0,63}` |
| payload tokens | exact str, ASCII whole-string `[0-9a-f]{64}` each |

上表已给出每个 field 的类型和值，不能以 JSON sample 代替。实现使用 length/ASCII character check 或等价 fullmatch，禁止 prefix match、Unicode normalization、大小写转换或自动 hash。合法 schema 无数字字段；`parse_int`/`parse_float` 只构造保存 token text 的私有 `JsonNumber`，不做 int/float conversion；任何 JSON number 于 shape 阶段 `bad_shape`，包括大整数和 `1e999`。

## 4. Diagnostic exact key/type/value 表

正常 output 的 exact key 顺序常量 `OUTPUT_KEYS` 严格等于下表顺序，恰好15项。函数返回精确 builtin dict；validator 唯一入口为 `validate_exact_v8_diagnostic`：要求 `type(value) is dict`；用一次 `snapshot=value.copy()`，此后只读 snapshot；所有 key 必须精确 `str`；按表逐项验证。validator 成功返回 `type(result) is tuple`、长度15的不可变 primitive snapshot，顺序为 `tuple(snapshot[key] for key in OUTPUT_KEYS)`；调用者只能读取 tuple，不再读取/传递原 dict。任一 key/value、copy、iteration 或读取异常导致验证失败，result slot 保持空且不传对象。每次函数调用前 result slot 必须先清空；只有验证返回 tuple 后才可写入本次 slot。异常、timeout、cancel、missing/truncated output 和 validator 失败一律保持空，不得复用旧 tuple/dict。dict 不能表示 duplicate key；duplicate 检查只针对 raw input JSON decoder。

| Exact key | 精确类型 | 固定值/允许值 |
|---|---|---|
| `schema` | str | `core.cfd.f8.r008.synthetic_non_qualifying_diagnostic.v8` |
| `mode` | str | `synthetic_only` |
| `evidence_class` | str | `synthetic_non_qualifying` |
| `diagnostic_outcome` | str | `non_qualifying` |
| `diagnostic_code` | str | 第 5 节 code allowlist |
| `payload_shape_valid` | bool | 由 code 唯一确定 |
| `scope_binding_matches` | bool | 由 code 唯一确定 |
| `qualification_row_binding_matches` | bool | 由 code 唯一确定 |
| `qualification_eligible` | bool | false |
| `qualification_authorized` | bool | false |
| `execution_authorized` | bool | false |
| `qualification_credit` | int | 0；`type(value) is int`，bool 不通过 |
| `gate_transition` | str | `none` |
| `registry_write` | bool | false |
| `harness_performed_external_io` | bool | false |

不得有缺失/额外字段；bool 字段必须 `type(value) is bool`，不得用 integer 代替。

## 5. 唯一诊断 code / boolean 组合

| Code | shape | scope | row | 条件 |
|---|---:|---:|---:|---|
| `invalid_arguments` | false | false | false | 参数精确类型/ASCII/full-token 检查失败 |
| `too_large` | false | false | false | raw bytes >4096 |
| `bad_encoding` | false | false | false | UTF-8 BOM 或 `UnicodeDecodeError` |
| `too_deep` | false | false | false | bounded scanner 遇第三层 |
| `bad_json` | false | false | false | `JSONDecodeError` 或专用 nonstandard-constant exception |
| `duplicate_key` | false | false | false | 完整 parse 后存在重复 key |
| `bad_shape` | false | false | false | 输入 exact schema/type/value 失败 |
| `internal_error` | false | false | false | 定义类别以外的普通异常 |
| `scope_mismatch` | true | false | true | 仅 scope 不相等 |
| `qualification_row_mismatch` | true | true | false | 仅 row 不相等 |
| `scope_and_row_mismatch` | true | false | false | 两者均不相等 |
| `synthetic_bindings_match` | true | true | true | 两个独立字符串各自相等 |

除 code、shape 和两个 match booleans 外，全部输出字段恒定。match 不产生任何资格/执行通过含义。

普通 `Exception` 映射完整固定 `internal_error`，不得携带 exception text/path/environment。`MemoryError`、`KeyboardInterrupt`、`SystemExit`、`GeneratorExit`、进程终止或 host/interpreter 崩溃不保证返回对象；调用边界拒绝且 result slot 空。

## 6. Consumer allowlist / verifier / 测试四元组

每行格式为 `consumer_id → exact accepted schema tuple/set → verifier_id@version → negative test node ID`。下表四元组是**拟定机器标识**，不等同于已部署 verifier 或已通过测试；状态必须显式登记。缺 schema、verifier/version、node ID，node 不存在/未执行/失败，或 consumer 未盘点，均令整体 consumer gate 为 `FAIL`。`sha256:<64 hex>` 表示指定源码文件的原始 bytes SHA-256，作为固定源码版本，不可换成模块名声明。

| consumer_id | Exact schema allowlist | Required verifier id@version | Negative pytest node ID | 当前状态 |
|---|---|---|---|---|
| Core global T1 evidence | `core.qualification.v1` | `core-qualification-evidence-verifier@v1`（实现缺失） | `test_core_formal_admission_audit.py::test_synthetic_evidence_rejected_before_global_t1_extraction` | BLOCKED：现有 generic evidence path 无该 verifier |
| Core structural audit adapter | `core.f3.legacy_hard_audit_adapter.v1`; `core.f3.structural_audit_adapter.v1` | `core-formal-structural-adapter-verifier@sha256:2c79c6d902e8576a03164b387a797eb96e47aa9b921567e8b65f2ba64373af37` | `test_core_formal_admission_audit.py::test_synthetic_adapter_rejected_before_case_binding` | BLOCKED：节点缺失；缺独立 raw-bytes ingress gate |
| Core readiness admission input | `core.formal_admission_audit.v1` | `core-formal-readiness-admission-gate@v1`（schema guard 实现缺失；当前 file hash `483f6d1ac38c83c22a87e222d2687dad39a6ef45e3e50073d896698e47a455db` 仅标识现状） | `test_core_formal_readiness.py::test_unknown_or_synthetic_admission_schema_rejected_before_gate_parse` | BLOCKED：现有 helper 先读 family fields |
| Core final release candidate | `core.formal_admission_audit.v1` | `core-formal-release-candidate-validator@sha256:e91dc5a0e3cac3592572bb5e81162b932b9ba2848f3053ecddaeffb45c70bee4` | `test_core_formal_release_candidate.py::test_synthetic_admission_receipt_cannot_release` | BLOCKED：node 缺失；当前仅内部 schema validator |
| F8 B stage | `core.cfd.f8.r008_materialization_receipt.v1` | `f8-r008-per-case-verifier@sha256:6c668743f1e8476df7c9b173dc91d1dee2d2748a0ba864af561337631c581752` | `test_f8_r008_per_case_bundle_verifier_v1.py::test_synthetic_diagnostic_rejected_for_b_stage` | BLOCKED：node 缺失 |
| F8 C stage | `core.cfd.f8.r008_solver_attempt_receipt.v1` | 同上，精确同一 verifier digest | `test_f8_r008_per_case_bundle_verifier_v1.py::test_synthetic_diagnostic_rejected_for_c_stage` | BLOCKED：node 缺失；C `solver_execution` 语义缺口仍独立 open |
| F8 D stage | `core.cfd.f8.r008_decode_table_provenance.v1` | 同上，精确同一 verifier digest | `test_f8_r008_per_case_bundle_verifier_v1.py::test_synthetic_diagnostic_rejected_for_d_stage` | BLOCKED：node 缺失 |
| F8 T1 metric matrix case input | `core.cfd.f8.r008_native_fluid_table_metric_bundle_verifier.v2` | `f8-r008-metric-bundle-verifier@sha256:175ee27d470e05f5fdb6e86a65cf2d6f96b7870bd9a9dae0886928e6486707a9` + `f8-r008-metric-matrix@sha256:667eb4a9c5d25216604161f3310bc143bd2836999355043c913d8afe3dab2c69` | `test_f8_r008_t1_metric_matrix_adapter_v2.py::test_synthetic_or_rewrapped_result_rejected_before_metric_parse` | BLOCKED：node 缺失；current output `full_t1_decision=false` |
| F8 fluid reducer input | outer `core.cfd.f8.r008_native_fluid_table_semantics.v1`; embedded `core.cfd.f8.r008_native_fluid_frame_table.v2` | `f8-r008-table-verifier@sha256:91c064acfe5fd4c8c70f5cf8a7b049ef789e55061f232991dfafb71167fdc455` + `f8-r008-fluid-reducer@sha256:f313497dd7cb0fc47593dcc39665486ecb122b4c45d600263c1d78c8ca9115cc` | `test_f8_r008_native_fluid_gate_reducer_v1.py::test_synthetic_verification_mapping_rejected_before_reduction` | BLOCKED：node 缺失；reducer 自身不认证调用方来源 |
| F8 gate registry | `NONE`（无 source-bound 输入 schema，故不允许 raw ingress） | `f8-r008-gate-row-source-verifier@v1`（实现缺失；当前 `aggregate_native_integrity_statuses` 仅结构聚合） | `test_f8_r008_native_integrity_registry_v1.py::test_synthetic_or_unbound_gate_rows_rejected_before_aggregation` | BLOCKED：不得将 bare mapping 升为 production gate |

源码 SHA 来自 2026-09-25 tracked file bytes。上表是已发现 direct consumers 的分项，不是全仓 consumer sweep；新的 consumer 必须先新增同样四元组和负向 node。任何 BLOCKED 行都不能被解释为 harness 输出已安全隔离或生产来源已验证。

## 7. 两阶段实现 gate 与权限

**实现前**只要求：V8 设计审查完成；全仓 consumer sweep 和上表 schema/verifier/test-node 四元组闭合；test plan 固定且被审查。此阶段不得运行 machine test 冒充其已通过。

**设计 gate 通过后允许的最小实现范围**：纯内存 V8 parser/validator、synthetic-only tests，以及为达成 fail-closed predicate 所必需的 admission/readiness/consumer raw-byte verifier 与拒绝 guard 的最小实现及负向测试。不得连接 synthetic 输出到 production gate，不得生成资格信用/registry 写入。

**实现后、任何 Diagnostic 或相关 consumer 结果被使用/持久化/接入前**：运行并通过完整 test node 表；覆盖所有 code 的输出 exact-key/type/constant/code-boolean 关系、Python bool≠int、JSON 优先级冲突、UTF-8 BOM decode 前检查、strict UTF-8、depth scanner 状态/EOF、duplicate nesting/object-array、JsonNumber、exception mapping、result-slot timeout/missing/stale fail-closed；对每个 consumer 运行 exact diagnostic、重复 discriminator、unknown/missing schema、production schema 重标、gate-shaped wrapper、复制/重序列化/缓存对象 corpus。记录实际 pytest node IDs、结果、清单 hash。任一测试缺失/未执行/失败，整体 FAIL。

任何 review/design PASS、synthetic test PASS 或 `synthetic_bindings_match` 均不代表 C-v1、native integrity、T1/readiness 或资格通过。solver/native/GenCase/worker/GPU/queue 仍需独立执行授权；本设计不触及冻结输入或 production evidence。
