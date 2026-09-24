# F8 R008 synthetic non-qualifying control harness V11（规范性增补草案）

V11 继承 V10、V9、V8；本文件只替换 V10 §4/§5 中 collector envelope、planner manifest-row evidence、F4 connector batch-decision 输入/call graph 的描述。旧版本均保留。

状态：V10 复核为 `REVISE`。reviewer 按 `gpt-5.6-terra` / high 配置请求，但 model/effort 无独立 attestation，意见只按普通技术审查记录。发现 F4 batch decision 的 production design/audits 输入未受保护；collector 把内嵌 JSON 对象误称为独立 raw-byte objects；planner manifest row 仍可内联 T1/audit marker；准备批次实际调用图与 V10 描述不符；qualification binding v1 不含 `scope_id`。V11 逐项修订。无 parser/verifier/consumer/test 实现；无 solver/training/worker/GPU/queue/native/GenCase 执行。F8 execution gate open、T1 false、零信用。

## 1. 替换 V10 §4：collector 只接受 raw-reference outer envelope

不得把 `binding`/`evaluation` 对象嵌入 envelope 后又声称有各自独立 raw bytes。新 envelope `core.f4.tallwall120.production_qualification_admission.v1` 仅承载精确 references：

| 字段 | exact 规则 |
|---|---|
| `schema` | 固定 `core.f4.tallwall120.production_qualification_admission.v1` |
| `mode` | `preparation_only` 或 `formal_release`，必须等于可信入口的预期 mode；不接受 caller 临时升级 |
| `scope_id` | 必须等于该固定入口的 F4 tallwall120 expected scope |
| `binding_ref` | exact `{stage,role,object_id,bytes,sha256}` ref；role 固定 `qualification_binding`，目标对象 schema 为 `core.f4.tallwall120.production_qualification_binding.v1` |
| `evaluation_ref` | formal 时必需，role 固定 `qualification_evaluation`、目标 schema `core.f4.tallwall120.qualification_evaluation.v2`；preparation-only 时必须为 null |

outer envelope 的原始 bytes 与两个被引用对象分别由可信 descriptor-root reader 取得；逐项验证 raw size/hash、schema、scope/role 和 exact nested shape。envelope 不含 `summary`、`binding` 或 `evaluation` inline payload。v1 既有无 schema wrapper/inline Mapping 不再兼容。preparation/formal 分别只产生 `VerifiedF4QualificationAdmissionPreparationV1` 与 `VerifiedF4QualificationAdmissionFormalV1`。该 envelope schema、producer、可信 root 与端到端绑定目前均不存在，故两个 collector gate 都 BLOCKED。V10 §4 两个拒绝 node ID 继续适用，并扩展覆盖不匹配 reference hash/role、引用内容与 envelope mode 不一致。

## 2. 替换 V10 §2：formal planner 禁止 manifest row 自带 evidence

`core_formal_planner.inspect_inputs` 不只拒绝 inline `evidence`/`audit` 参数；也必须在解析或汇总任何 T1 前验证每个 manifest row。正式规划只接受新增 exact schema `core.formal_training_manifest.v1`：top-level 恰为 `schema,dataset_id,formal_release,cases`；`formal_release` 必须精确 bool true。每个 case 恰为 `case_id,physical_case_id,lineage_group_id,family,scope_id,recipe_id,split,stage,qualification_only,qualification_case,hdf5,sha256,known_inputs_sha256,known_inputs_ref,case_audit_ref`。身份字段、HDF5 path/hash 字段按 exact primitive type/format 校验，`split` 属于 `{train,validation,test,id_test,ood_test}`；`known_inputs_ref` 采用 `core.dataset.v2` 的 existing exact ref contract。`stage` 固定 `production`，`qualification_only` 与 `qualification_case` 必须精确 bool false；`case_audit_ref` 必须是独立 raw-byte object reference `{schema,role,object_id,bytes,sha256}`，其中 schema=`core.evidence_reference.v1`、role=`case_audit`，无 inline payload/path。Manifest row 禁止 `_T1_KEYS`、audit pass/status markers、qualification evidence/provenance objects 或未知字段。

全局 T1 只可通过 manifest 外独立的 raw-byte `core.qualification.v1` 生成 scope-bound `VerifiedCoreQualificationV1`；逐 case audit 只能由 `case_audit_ref` 指向的 raw `core.case_audit.v1` 生成 `VerifiedCaseAuditV1`，再验证 case/scope/recipe binding。规划器必须将已验证的训练字段确定性投影为精确 `core.dataset.v2`，去除所有 qualification/audit/reference-only metadata；job spec 只绑定此 sanitized manifest 的 bytes/hash，禁止继续传原 `core.formal_training_manifest.v1` 给 reader（当前 reader 仅识别 dataset v1/v2）。任何旧 `core.dataset.v1/v2` 直接作为 planner admission manifest、inline evidence/audit 参数、row 内 T1/audit status 或 reference 伪装/缺失均在读取 family/T1/audit gate 字段前拒绝整个 plan，不得 fallback 到旧 schema 或忽略异常字段继续执行。

在 V10 已提议的 `test_core_formal_planner.py::test_synthetic_t1_evidence_rejected_before_formal_plan` 之外，新增节点 `test_core_formal_planner.py::test_manifest_t1_and_audit_markers_rejected_before_formal_plan`，覆盖 manifest row 直接放入 T1、audit-pass、embedded evidence 三种路径；并新增 `test_core_formal_planner.py::test_verified_projection_emits_exact_dataset_v2_without_evidence_fields` 验证 deterministic dataset projection。拒绝节点必须断言发生在 `family_t1`、`launch_allowed` 或 job-spec 派生之前；这些节点当前均不存在。V10 §2 所列 exact external evidence schemas/capabilities 继续适用。

## 3. 替换 V10 §5：F4 batch-decision 的完整 capability tuple

V10 的 batch-decision capability 需扩展；生产设计及可选审计同样影响 8→32 放行，不得只验证资格 receipt。

| 输入 | exact source/schema | 接受形式及绑定 |
|---|---|---|
| production design | `core.production_design.v1` | raw bytes 经 F4 固定 scope/32-case 参数、source/hash validator 后为 `VerifiedF4ProductionDesign` |
| qualification | `core.f4.tallwall120.qualification_evaluation.v2` + `core.f4.tallwall120.production_qualification_binding.v1` | 经 root tick/re-evaluation 与 manifest、scope、reevaluation digest 交叉验证后为 `VerifiedF4QualificationV2` |
| 可选 audits | 每个 case `core.case_audit.v1` | raw-byte verifier 逐 case 绑定 production-design case_id/scope/physical_case_id；整组冻结分母后为 `VerifiedF4AuditSetV1`，空集只能表示“无 audit 输入”而不得表示已通过 |

private `_batch_decision_verified` 的唯一入参是不可变 `VerifiedF4BatchDecisionInputV2`，其内容精确为上述 design capability、qualification capability 和 audit-set capability-or-absent tag。该函数不得接受 `Mapping`，不再做 `dict(...)` 转换；所有判断只经固定 accessor。公共准备入口应先通过 trusted raw-byte reader 得到 design/evidence capabilities，再做 batch decision；随意重算 hash 或外层声明 `verified=true` 不得构造 capability。

新增独立拒绝 nodes：

- `test_f4_tallwall120_production_connector.py::test_unverified_production_design_rejected_before_batch_decision`
- `test_f4_tallwall120_production_connector.py::test_unverified_audit_mapping_rejected_before_batch_decision`

V10 已提议的 `test_unverified_mapping_rejected_before_batch_decision` 专门覆盖 qualification mapping，三种拒绝不可互相替代。上述节点当前均不存在；source hashes 继续只是 review anchors。

## 4. F4 connector 的目标调用图与 binding v1 scope 语义

V10 §5 描述的是**待实现目标调用图**，不是当前代码事实。当前 `prepare_production_batch` 执行 `tick_qualification()` 并直接调用 Mapping 版 `batch_decision`，没有调用公开 `validate_evaluation()`。目标 v2 必须按以下一种受信路径实现并单独复核：

1. external receipt path：trusted raw evaluation/reference ingress → exact evaluator verifier → `VerifiedF4QualificationV2`；或
2. root-owned tick path：固定 manifest/runtime/archive roots → trusted evaluator/re-evaluation → 同一 schema-specific `VerifiedF4QualificationV2`。

两路径合流后再和 `VerifiedF4ProductionDesign`、`VerifiedF4AuditSetV1` 组成 batch decision capability。不得在两路径之间传普通 summary dict。

`core.f4.tallwall120.production_qualification_binding.v1` 当前不含 `scope_id`，V11 不得静默扩展其 v1 schema。Verifier 从可信固定入口的 expected scope 与 evaluation 的 `scope_id` 验证 scope；binding 再以其 exact manifest digest、reevaluation digest、T1/matrix fields 与独立 verified evaluation 交叉绑定。若现有字段不足以唯一绑定 evaluation/manifest，则新增 schema v2，而不是修改 v1。此结论是静态设计要求，不声称当前 connector 实现已满足。

## 5. 安全/执行边界

本增补仅扩展负向 schema/consumer 设计。不得运行 formal planner、生成 job specs、调用 `prepare_production_batch`、调用 canary/worker/training/solver/GPU/queue/native/GenCase；不得修改已消耗的一次性 F3/F4 授权、F4 canary 预检源码/receipt 或历史 namespace。root capability 仍表示可信 key/descriptor 能力，不是 sudo/root 用户要求。无可信 launcher/root capability 时所有 production ingress 保持 disabled。
