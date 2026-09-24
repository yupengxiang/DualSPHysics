# F8 R008 synthetic non-qualifying control harness V12（规范性增补草案）

V12 继承 V11、V10、V9、V8；只替换 V11 中 collector 引用合同、formal planner sanitized projection、F4 connector preparation capability 与相应拒绝测试。此前版本保留为历史草案。

状态：V11 只读审查为 `REVISE`（reviewer 按 Terra/high 配置发起，但无独立 model/effort attestation，故只记普通技术意见）。本版处理五项发现：`prepare_production_batch` 的 template/status/digest 等遗漏输入、collector ref/envelope 未完全 exact、dataset v2 projection 缺严格递归 schema、raw 与 canonical digest 混用，以及对应 public-entry 负测不精确。未实现 parser/verifier/consumer/tests；未运行 planner、collector、batch preparation、solver/worker/GPU/queue/native/GenCase。F8 gate 仍 open、T1 false、零信用；不重写或重试已消耗的 F3/F4 one-shot 授权。

V12 草案随后接受一次按 Terra/high 配置发起的只读审查（无独立身份/effort attestation，意见不构成可验证 Terra PASS）。审查指出 admission/ref 双副本摘要未绑定、nested schema 与 mode/nullability 不够 exact、dataset `known_inputs_sha256` 未与重建对象 hash 相等、C query journal未进入 V4 object graph/cache semantics不符、inline XML table raw bytes及 PID-generation 唯一性不足。V12/C-v4 当前工作稿已据此补入 normalized admission v2/v1 schema 与 digest 分层、KnownInputs contract hash 重算、V4 journal/ref/version、cache provenance、XML source-slice hash 和 generation birth sequence；这些只是待复核设计，未实现。

## 1. 替换 V11 §1：exact collector envelope 与引用对象

新 outer schema 为 `core.f4.tallwall120.production_qualification_admission.v1`，顶层 exact keys 为 `{schema,mode,scope_id,binding_ref,evaluation_ref}`；拒绝未知、缺失、重复 JSON key。envelope 本身由固定 consumer entry 的可信 descriptor-root raw reader 取得，入口固定 role/scope/mode，不接受 caller 选择 consumer、root、role 或升级 mode。

每个非 null ref 的 exact keys 为 `{stage,role,object_id,target_schema,bytes,raw_sha256,canonical_json_sha256}`，均必需；ref 中不准有 path、inline JSON 或扩展字段。

| 字段 | 精确约束 |
|---|---|
| `stage` | 固定字符串 `qualification` |
| `role` | binding ref 固定 `qualification_binding_admission`; evaluation ref 固定 `qualification_evaluation_admission`; evaluation source ref 固定 `qualification_evaluation_raw` |
| `object_id` | 1–64 ASCII `[a-z0-9][a-z0-9._-]*`，并须命中固定入口的 object allowlist；不得是路径或 `.`/`..` |
| `target_schema` | binding ref 固定 `core.f4.tallwall120.production_qualification_binding_admission.v2`; evaluation ref 固定 `core.f4.tallwall120.qualification_evaluation_admission.v1`; evaluation source ref 固定 legacy result schema `core.f4.tallwall120.qualification_evaluation.v2` |
| `bytes` | JSON integer（bool 不算 integer），`1..1073741824` |
| `raw_sha256` | 对 descriptor-root 读取的原始 bytes 直接计算 SHA-256，64 位小写十六进制 |
| `canonical_json_sha256` | strict parse/schema validation 后，对完整被引用 JSON object 使用既有 F4 `canonical_digest` 字节规则计算 SHA-256：UTF-8 编码 `json.dumps(value, sort_keys=True, separators=(",",":"), allow_nan=False)` 的输出；不是原文件 hash，也不是 nested `reevaluation_sha256` 的别名 |

`mode` 类型必须精确为 builtin string，enum 仅 `preparation_only|formal_release`（bool、null、其他 JSON 类型和值均拒绝）；`scope_id` 必须精确为 builtin string 且等于固定 F4 tallwall120 scope；`binding_ref` 永远非 null。`preparation_only` 要求 outer `evaluation_ref=null`；`formal_release` 要求非 null evaluation ref。binding object 内永远有一个 `evaluation_ref`，且在 formal 模式必须与 outer ref 的七个字段逐字段完全相等。所有对象先由 FD-relative、no-follow、mount-bound reader 打开；按以下次序拒绝：入口 allowlist 与 outer raw bytes → strict JSON（duplicate key/非有限数均拒绝）→ outer exact keys/schema/mode/scope → ref exact keys/type/domain/role/stage/target schema → 被引对象 raw size/hash → strict parse 与 target schema → canonical JSON digest → nested semantic/cross-binding。不得在 digest、schema 和 scope/ref 绑定前读取 T1、matrix、eligibility 或审计 pass 字段。

当前 CLI tick 写出的 `core.f4.tallwall120.production_qualification_binding.v1` wrapper `{schema,binding,result}` **不是 V12 admission object，必须 fail-closed 拒绝**，不能把旧 binding-v1 `verified=true` 当作可信对象。目标 binding reference 指向尚不存在的新 wrapper schema `core.f4.tallwall120.production_qualification_binding_admission.v2`，完整对象 exact keys 为 `{schema,binding,evaluation_ref}`；`schema` 固定该 v2 ID。nested `binding` exact keys 为 `{schema,scope_id,revision_id,manifest_sha256,evaluation_raw_sha256,reevaluation_sha256,evaluation_admission_canonical_json_sha256,matrix_complete,T1_numerical,cell_indices,passed_cell_indices,missing_indices,failure_indices,checks,artifact_bindings_verified,declaration_consistent}`。其中 schema 固定 binding-admission v2，scope/revision 固定 F4 值，各 digest 为 64 位小写 hex；所有 index 数组由 `0..14` 内精确 builtin integer（bool 禁止）升序唯一元素构成，`checks` exact keys 为 `static_contract,matrix_complete,all_case_hard_mass_event_gates,spatial,independent_checks,time_and_output,cell12_reuse_verified,cell12_reuse_does_not_inherit_qualification` 且值精确 bool；matrix/T1/artifact/declaration 均为 bool。未知、缺失字段或 builtin 类型不匹配均拒绝。

`evaluation_ref` 指向新的 strict normalized admission object，而不是把 evaluator 的任意诊断 JSON 嵌在 binding wrapper。`core.f4.tallwall120.qualification_evaluation_admission.v1` exact keys 为 `{schema,scope_id,revision_id,manifest_sha256,evaluation_source_ref,evaluation_raw_sha256,evaluation_canonical_json_sha256,cell_indices,passed_cell_indices,missing_indices,failure_indices,checks,matrix_complete,T1_numerical,artifact_bindings_verified,declaration_consistent,promotion_status}`。`evaluation_source_ref` 是 exact V12 ref，指向 raw evaluation-v2 原始字节；其 `bytes` 必须等于实际读取字节长度，`raw_sha256` 与 `canonical_json_sha256` 必须分别等于本 admission object 的 `evaluation_raw_sha256` 与 `evaluation_canonical_json_sha256`。后两者专指 raw evaluator result 的摘要，不是本 admission object 自身的摘要；admission object 的 canonical digest 只由其外部 ref 的 `canonical_json_sha256` 绑定，避免自引用。raw result 只作 provenance：完整原始 bytes 由 source ref 的 bytes/raw digest 绑定，strict parse 后的 canonical digest 由 source ref 与 admission projection 双向绑定；任何 gate decision 只能来自 trusted root-owned reevaluation producer 对原始 manifest/runtime/archive inputs 的重新验证后生成的 admission projection，不能由 raw result 的自述 boolean 直接产生 capability。projection 的固定字段类型/域沿用上段；`passed_cell_indices`、`missing_indices`、`failure_indices` 两两不相交且并集必须等于 0..14；`cell_indices` 等于 `passed_cell_indices ∪ failure_indices`；`matrix_complete` 精确等于全部 15 个 index 均 passed 且 missing/failure 为空；`T1_numerical` 精确等于 `matrix_complete && all(checks) && artifact_bindings_verified && declaration_consistent`；若 artifact binding 或 declaration consistency 为 false，root-owned producer 必须拒绝 mint capability（不得仅返回 false admission 供 release consumer解释）。`promotion_status` enum 仅为 `blocked_until_14_scheduled_products_and_all_gates|blocked_until_all_gates|qualified_candidate_pending_root_review`，并按以下纯函数唯一派生：固定 `scheduled_solver_indices=[0,1,2,3,4,5,6,7,8,9,10,11,13,14]`、`reused_canary_indices=[12]`；若 `missing_indices ∩ scheduled_solver_indices` 非空，则为 `blocked_until_14_scheduled_products_and_all_gates`；否则若 `T1_numerical=true`，则为 `qualified_candidate_pending_root_review`；其余情况一律为 `blocked_until_all_gates`。该 mapping 使用本 scope 已登记的 14 个 scheduled products 与 cell-12 reused canary 分工；caller/raw result 不得提供或覆盖此派生值。

两种 mode 都必须满足：binding 与 wrapper 内部 ref 指向的 normalized admission projection 之 `scope_id,revision_id,manifest_sha256,evaluation_raw_sha256,matrix_complete,T1_numerical,cell_indices,passed_cell_indices,missing_indices,failure_indices,checks,artifact_bindings_verified,declaration_consistent` 逐字段完全相等；并且 `binding.reevaluation_sha256 == projection.evaluation_canonical_json_sha256`、`binding.evaluation_admission_canonical_json_sha256 == wrapper evaluation_ref.canonical_json_sha256`。这些要求也适用于 preparation-only，因为 wrapper 内仍有必需且完整验证的 admission ref。formal mode 另外要求 outer evaluation ref 的全部七字段与 wrapper 内 ref 完全相同；outer ref 的 `canonical_json_sha256` 等于 nested `binding.evaluation_admission_canonical_json_sha256`；projection 的 `evaluation_canonical_json_sha256` 与 `evaluation_raw_sha256` 分别等于 `evaluation_source_ref` 的 canonical/raw digest。normalized admission object 的 canonical digest 始终是其 ref 的 `canonical_json_sha256`，不内嵌自摘要。这样明确区分 admission projection digest 与 raw evaluator-result digest，禁止把二者混作一项。preparation-only 时 outer ref 必须 null。所有 legacy v1 tick wrapper、schema relabel、inline Mapping、引用拆分替换及 bool-only 伪造均 fail-closed。以上 admission-v2 producer/verifier/source-root 尚不存在，故两分支目前 BLOCKED。

拒绝结果采用固定诊断：`E_COLLECTOR_OUTER_SCHEMA`, `E_COLLECTOR_REF_SHAPE`, `E_COLLECTOR_REF_ROLE`, `E_COLLECTOR_REF_HASH`, `E_COLLECTOR_REF_SCHEMA`, `E_COLLECTOR_REF_CANONICAL_DIGEST`, `E_COLLECTOR_EVALUATION_COPY_MISMATCH`, `E_COLLECTOR_MODE_BINDING`, `E_COLLECTOR_SCOPE_BINDING`。分别新增 `test_core_f4_tallwall120_production_collector.py::test_ref_raw_hash_and_role_mismatch_rejected_before_collection`, `test_core_f4_tallwall120_production_collector.py::test_ref_target_schema_and_mode_mismatch_rejected_before_collection` 与 `test_core_f4_tallwall120_production_collector.py::test_binding_and_outer_evaluation_copy_mismatch_rejected_before_collection`。三者必须从实际 public collector entry 证明拒绝发生在任何 eligibility 派生/collection 之前；目前均不存在。producer、root trust 与实现仍 BLOCKED。

## 2. 替换 V11 §2：strict formal manifest 与可验证 dataset-v2 投影

Formal ingress 只接受 exact `core.formal_training_manifest.v1`，沿用 V11 §2 的 exact manifest/case keys 与外置 qualification/audit references；重复 JSON key、任意未知字段、row/global inline gate marker 均在解析 T1/audit 前拒绝。V11 所称 sanitized projection 在此具体化如下。

投影输出顶层 exact keys 为 `{schema,dataset_id,case_count,formal_release,diagnostic_only,cases}`：`schema="core.dataset.v2"`，`dataset_id` 为非空 ASCII 标识符，`case_count == len(cases) > 0`，`formal_release=true`，`diagnostic_only=false`。不得携带 `source_manifest_sha256`、qualification/audit/evidence/ref-only record、producer summary 或额外 key。

每个投影 case 顶层 exact keys 为 `{case_id,physical_case_id,lineage_group_id,family,split,hdf5,sha256,known_inputs_sha256,known_inputs_ref,scope_id,recipe_id}`。标识符为非空 ASCII 字符串；`split` 精确属于 `{train,validation,test,id_test,ood_test}`；`hdf5` 与 nested asset paths 是非空 UTF-8 POSIX 相对路径，拒绝前导 `/`、反斜杠、NUL、空／`.`／`..` segment，逐段通过固定 data-root FD no-follow 打开；两个 digest 必须为 64 位小写 hex；`scope_id`、`recipe_id` 必须来自已验证登记信息，并分别与 qualification/audit capability 完全绑定。禁止任何 `qualification*`、`T1*`、`audit*`、`evidence*`、`provenance*`、`receipt*`、`reference*` 字段及未知扩展字段。

`known_inputs_ref` 顶层 exact keys 为 `{contract_version,geometry,control,physics,numerics,coordinate_frame}`，`contract_version` 固定 `core.inputs.v1`。`geometry` 与 `control` 各自 exact keys 为 `{format,path,sha256,version}`，`format="npz"`，`version="core.input_asset.v1"`，`path` 为 data-root 相对路径，`sha256` 为 64 位小写 hex。`physics` 仅允许 `core_contract._KNOWN_INPUT_FIELD_TYPES.physics` 中登记的字段，`numerics` 仅允许 `.numerics` 中登记字段；未知字段必拒绝。两组字段类型逐项遵循该表（有限 JSON number、长度 3 的有限数 vector、string 或 boolean），不接受 null、NaN/Infinity、嵌套 object/array 或 bool-as-number。`coordinate_frame` 为非空字符串，必须与几何输入的 frame 完全一致；`numerics.recipe_id` 必须等于 case `recipe_id`，若 physics 声明 `scope_id`/`family` 亦须与 case 一致。strict validator 还必须在固定 data-root capability 下 no-follow 打开 geometry/control NPZ，先验证 raw size/hash/mount，再以与 `core_dataset.known_inputs_from_record` 相同语义、但 descriptor-relative 的 reader 重建 `KnownInputs`，并要求 `known_inputs_sha256 == core_contract.contract_hash(reconstructed_known_inputs)`；只检查 digest 格式或调用不重算此字段的通用 `validate_manifest` 不足。此操作只读 geometry/control assets，不打开 HDF5 trajectory。不得通过忽略 `core_dataset.validate_manifest` 不检查的未知字段放行。

实现必须增加 formal-planner 专用 strict validator：先按上述 recursive allowlist 校验 projection 的每一层，再调用通用 dataset reader validator；通用 validator 的“最低字段满足”不能代替 strict validator。`case_audit_ref` 只用于外置 `VerifiedCaseAuditV1` 校验，不进入投影。投影采用固定 key/value serialization 生成 deterministic bytes；对相同 verified input 与 capabilities，bytes/hash 必须相同。job spec/reader 只绑定并读取该 `core.dataset.v2` projection，不再读取 formal manifest 原文。

新增 `test_core_formal_planner.py::test_verified_projection_exact_recursive_schema_and_deterministic_bytes`，覆盖未知顶层/case/known-input nested key、被禁止 evidence marker、非法 asset ref、类型混淆、projection 重复生成 bytes/hash 恒定，以及 projection 可经 strict validator 与 dataset validator；断言在 planner family/T1/job-spec/`launch_allowed` 派生前拒绝。该测试当前不存在。

## 3. 替换 V11 §3：decision capability 与 preparation capability 分层

`VerifiedF4BatchDecisionInputV2` 只含不可变 `VerifiedF4ProductionDesign`、`VerifiedF4QualificationV2`、`VerifiedF4AuditSetV1 | AuditSetAbsentV1`。该私有 decision consumer 不接 Mapping、不复制普通 dict。这个 capability 仅授权计算纯 8→32 batch decision，不足以构造任何 preparation product。

真正的准备输入必须另建不可伪造的 `VerifiedF4BatchPreparationInputV2`，严格含：

1. 上述已验证 batch-decision capability 及其纯函数决策结果；`batch_status` 从结果派生，不接受 caller string。
2. `VerifiedF4TemplateV1`：从固定 trusted template roots 读取的 raw template config、prepared template object、二者 raw bytes/hash、scope/recipe/revision 与 prepared closure 全部交叉验证。不得传入普通 `template_config` Mapping。template 内所有会进入 `core_cfd.prepare` 的字段须被 exact schema 验证并与登记 template digest 相等。
3. `qualification_receipt_sha256` 从 `VerifiedF4QualificationEvaluationV2` 所绑定的 exact evaluation-admission object raw bytes 派生；其内部 `evaluation_raw_sha256` 另行绑定 evaluator 原始 result，不得混用。`template_prepared_sha256` 从受信 prepared-template raw bytes 派生；禁止 caller 提供或覆写。若产物还记录 `production_design_sha256`，它按固定 canonical digest 从同一 `VerifiedF4ProductionDesign` 派生。
4. manifest/runtime/archive/lab/template/output roots 均为 trusted entry 固定的 descriptor/root capabilities；不得用 caller path 替换。proposal output root 必须为 supervisor 创建的新鲜、隔离、不可链接目录 capability；普通 output path、existing nonempty output 或跨 mount root 一律先拒绝。

public `prepare_production_batch` 的旧 Mapping/path 入口关闭：在读取 `production_design`、`qualification`、`template_config`、digest、status 任何字段，或导入 `core_cfd`、创建输出目录、派生 config/job spec 之前，返回固定 `E_PREPARE_UNVERIFIED_INPUT`。不提供 mapping fallback，也不允许把 boolean/receipt 中 `verified=true` 转为上述 capability。

新增独立 public-entry nodes：

- `test_f4_tallwall120_production_connector.py::test_legacy_prepare_mapping_rejected_before_template_read`
- `test_f4_tallwall120_production_connector.py::test_caller_batch_status_rejected_before_decision_or_output`
- `test_f4_tallwall120_production_connector.py::test_caller_qualification_digest_rejected_before_config_derivation`
- `test_f4_tallwall120_production_connector.py::test_caller_template_digest_rejected_before_config_derivation`

各节点需用会触发 observable read/side-effect 的 sentinel 验证拒绝时序；不能只断言最终异常。以上以及 V11 的 design/qualification/audit/collector/planner nodes 均为提议名，尚未实现或运行。该设计不授权调用现有 preparation、GenCase、worker、training、solver、GPU、queue、native 或任何生产任务。

## 4. 信任与状态边界

所有 consumer capabilities、raw-byte verifiers、strict schema validators 与负向测试目前缺失。Source SHA 和 canonical digest 都只是内容绑定，不是 producer 身份、runtime loaded-code 身份或可信 root attestation。无可信 launcher/root capability 时 production ingress 保持 disabled；root capability 不等同 sudo/root 用户权限。历史 F3 row30 与 F4 supportcap 一次性授权和回执保持不可变且不重试。
