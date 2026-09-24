# F8 R008 synthetic non-qualifying control harness V10（规范性增补草案）

V10 继承 V9 全文与 V8 第 3、5 节 parser/input/code 规则；本文件仅以明确列出的条款替换 V9 第 2/3 节相应描述。V8–V9 保留为历史版本。

状态：V9 只读审查为 `REVISE`。按 `gpt-5.6-terra` / high 配置请求 reviewer，但 reviewer model/effort 无独立 attestation，故仅记技术意见、不声称可验证的 Terra High PASS。发现并修订：遗漏 `core_formal_planner` 正向 T1→formal training plan 入口；F4 collector 的真实 outer qualification wrapper 无强制 schema；F4 range-root 的 schema 实为 `core.qualification.v1`；dispatch helper 不得接受调用方选择 consumer ID；evaluation 与 batch-decision 各需独立拒绝测试。V10 仍为设计草案，无 parser/consumer/test 实现；production verifier 因无可信 launcher/root capability 仍关闭，R008 gate open、T1 false、零信用。无 solver/worker/GPU/queue/native/GenCase 执行授权。

## 1. V9 §2：consumer identity 固定于不可导出入口

删除任何可被外部调用的 `accept_for_consumer(raw_bytes, consumer_id, ...)` 形式。公共边界只能是每个 consumer 单独命名的固定入口，例如 `accept_for_core_formal_planner(raw_bytes, trusted_context_capability)`；入口闭包捕获唯一不可变 dispatch row 与 consumer identity，caller 不提供、不选择或覆盖 consumer ID/schema/verifier/root/role/scope。

共享 helper 是 verifier module 的不可导出私有函数，不从 package/public API 暴露，不接受 consumer ID 字符串；只接受入口闭包持有的 private dispatch capability 和 raw bytes。trusted context capability 必须绑定同一 consumer identity、expected scope 和 root capability。跨 consumer capability、反射得到的未验证对象、普通 Mapping、CLI 参数或 receipt 内自述一律拒绝。若当前 Python runtime 无法建立上述闭包/加载身份信任，则所有入口保持 disabled；该限制与是否使用 sudo/root 用户无关。

## 2. V9 §3：补齐 formal-planner T1 ingress

| consumer / exact T1-bearing schemas | 入口与旧路径 | pre-validation 禁读 / success type | verifier anchor / negative node | 状态 |
|---|---|---|---|---|
| Core formal training planner：global `core.qualification.v1`；case-level `core.case_audit.v1`；manifest `core.dataset.v1/v2` | `core_formal_planner.inspect_inputs` / `build_plan`；path 输入改 trusted raw-byte reader，所有 inline evidence/audit Mapping 拒绝；manifest/config 非 T1 数据也须 exact schema 验证 | 禁读 `_T1_KEYS`、family/scope/recipe、audit pass 和 qualification markers；成功后只接收 scope-bound `VerifiedCoreQualificationV1`, per-case `VerifiedCaseAuditV1` 与 `VerifiedDatasetManifestV1/V2`，planner 才可生成 job plan | `core-formal-planner-evidence-verifier@v1` (source anchor `sha256:b5363a4724d6ce27bea58080387e29449d16fc83406f8e3ef91133e1dc9dc15e`); `test_core_formal_planner.py::test_synthetic_t1_evidence_rejected_before_formal_plan` | BLOCKED：当前接受 path 或 inline Mapping，T1 可来自 global/family evidence |

该入口虽不直接启动训练，但 `build_plan` 可生成 `launch_allowed=true` 和 formal job specs，因此按启动决策 ingress 处理。任何 review/test 通过都不调用其 job submission/runner，不生成真实训练任务。

## 3. V9 §3：F4 material range-root schema 更正

`f4_tallwall120_material_preflight_v1.inspect_source` 的 range-root exact schema 固定为 `core.qualification.v1`；checked-in receipt 的当前原始 bytes digest 是 `sha256:88bf903dbf2345dff9d0c9ac507ea3d9cef1387ba6fdcbd4ea8168f9828c770d`，仅为文件 review anchor。该输入由 preflight 直接读取并消费 `T1_numerical`/`matrix_complete`。未闭合项应表述为 **trusted producer/source chain 与 loaded-code identity 未验证**，不是 schema 未知。该 consumer 的目标验证前禁读字段及 negative node 沿用 V9 表项；实现后需 raw-byte verifier 绑定该 exact schema、scope、完整来源 bytes，并单独拒绝重标/复制/伪造 root receipt。

## 4. V9 §3：F4 collector 的新 outer envelope 与分支测试

现有 `collect_f4_production(..., qualification_receipt=...)` 接受无 schema outer Mapping/path；非 formal 分支读取 `summary`/`binding`，formal 分支再检查 nested evaluation/binding，故不能把 nested schema 冒称为 outer ingress schema。关闭此接口的 schema-less/inline fallback，并新增一个 versioned raw-byte outer envelope：

| 字段 | exact 规则 |
|---|---|
| `schema` | `core.f4.tallwall120.production_qualification_admission.v1` |
| `mode` | exact enum `preparation_only` 或 `formal_release`，与调用方 `formal_release_requested` 必须一致 |
| `scope_id` | 固定 F4 tallwall120 scope |
| `binding` | exact `core.f4.tallwall120.production_qualification_binding.v1`，其 scope、manifest、reevaluation、matrix/T1 字段按可信 verifier 复算 |
| `evaluation` | `formal_release` 时必需且 exact `core.f4.tallwall120.qualification_evaluation.v2`；`preparation_only` 时只能为 null |
| `summary` | 禁止作为输入字段；由 verifier 从上述 validated binding/evaluation 派生 |

该 envelope 不是现有 schema 的别名；其 producer/raw hash/trusted launch chain 尚未定义，所以两条路径保持 BLOCKED。outer 与 nested objects 均须由受信 raw-byte reader 取得，验证前不得读取 mode、T1、matrix、scope 或 eligibility。成功返回 `VerifiedF4QualificationAdmissionPreparationV1` 或 `VerifiedF4QualificationAdmissionFormalV1`。分别设置两个 exact pytest node：

- `test_core_f4_tallwall120_production_collector.py::test_synthetic_qualification_rejected_before_preparation_collection`
- `test_core_f4_tallwall120_production_collector.py::test_synthetic_qualification_rejected_before_formal_collection`

二者均必须证明 exact V10 Diagnostic、schema 重标、inline wrapper 与 nested fake `binding.verified=true` 在读取 gate fields 前拒绝；目前测试均不存在。

## 5. V9 §3：F4 connector 分离 evaluation ingress 与 batch decision

V9 将两个不同边界合并为一行/一个 node，不足以证明先验拒绝；现分为两项：

| 边界 | exact schema / 接受对象 | 禁止的旧路径 / pre-read 字段 | capability / 独立 negative node | 状态 |
|---|---|---|---|---|
| `f4_tallwall120_production_connector.validate_evaluation` → `_receipt_summary` | raw evaluation `core.f4.tallwall120.qualification_evaluation.v2`；manifest 与 per-cell archive/execution references 按各自 exact schema/role 校验 | 不接收 caller Mapping；验证前禁读 cells、T1、matrix/claim；所有 ref 先 raw-byte/hash/role 校验 | `VerifiedF4QualificationEvaluationV2`; `test_f4_tallwall120_production_connector.py::test_synthetic_evaluation_rejected_before_t1_derivation` | BLOCKED：当前公开函数收 Mapping |
| `f4_tallwall120_production_connector.batch_decision` | 只接内部 root tick 返回的 `VerifiedF4QualificationBindingV1` / `VerifiedF4QualificationEvaluationV2` 组合；不设 raw JSON ingress | 该函数改为私有 capability consumer；拒绝 plain dict/Mapping；在 exact capability 检查前不得读 binding/T1/matrix | `VerifiedF4BatchDecisionInput`; `test_f4_tallwall120_production_connector.py::test_unverified_mapping_rejected_before_batch_decision` | BLOCKED：当前读取调用方 Mapping；独立节点缺失 |

`prepare_production_batch` 的 root tick → `validate_evaluation` → private capability → `batch_decision` 是唯一允许路径；不得通过 public `batch_decision` 注入伪造 summary。源脚本 SHA 仍只是 review anchor，不是 runtime identity。

## 6. Tests 与总体 gate

V10 所有新增 node ID 都是待创建测试名，不得报告为已存在或通过。V9 两阶段规则继续有效：实现前只审设计、入口覆盖、node ID 与攻击 corpus；实现后才要求节点存在且运行通过。F4 collector 的 preparation/formal 两个节点、F4 connector 的 evaluation/batch 两个节点分别执行；一个成功不能代替另一个。Core planner 的 negative test 必须证明 `launch_allowed`/job-plan 字段尚未被读取或生成时已拒绝。

这些增补不改变 V9 的其他 BLOCKED 项：trusted launcher/root capability 缺失时 production ingress 始终 disabled；已消耗的一次性 F3 row30/F4 supportcap 授权及历史 namespace/receipts 不得修改、重建或重试。root capability 不是 sudo 请求。
