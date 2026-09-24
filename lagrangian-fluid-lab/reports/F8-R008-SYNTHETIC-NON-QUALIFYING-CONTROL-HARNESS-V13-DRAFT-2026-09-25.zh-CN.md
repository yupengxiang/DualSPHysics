# F8 R008 synthetic non-qualifying control harness V13（规范性增补草案）

状态：V13 首轮只读交叉复核为 `REVISE` 后已修订；focused text review 确认 serialization-only digest vector 与 `hdf5_size_bytes` builtin-int 规则明确。它仍是 V12 的 synthetic-only 设计增补，不是实现或资格合同。它只替换下列 V12 语义，不改历史收据、冻结输入、资格矩阵、失败分母或已消费授权。旧 Mapping/path API 的禁用要求尚未在现有源码落实。未实现、未运行测试；未运行 planner/collector/preparation、GenCase/native/solver/worker/GPU/queue。R008 `readiness_pass=false`、`T1_numerical=false`、资格信用为零。

## 1. 唯一 qualification bundle 与各层摘要

V12 §1/§3 中并列的 `VerifiedF4QualificationV2`、`VerifiedF4QualificationEvaluationV2` 与 `qualification_receipt_sha256` 被替换为一个由固定 collector consumer 的可信 root reader 创建的不可变 `VerifiedF4QualificationBundleV3`。缺少该 root capability 时，公开 collector、batch-decision 和 preparation 入口一律在读取 gate 字段、导入执行器或创建输出前 fail closed；普通 Mapping、caller digest、schema 自述或 `verified=true` 不能 mint capability。

bundle 只能由一次验证得到，保留同一 exact outer admission envelope 的原始 bytes 与 immutable parsed value，并携带以下有序引用对象：`binding_admission`、`evaluation_admission`、`evaluation_source_raw`。每个 JSON 对象都由其完整 raw bytes strict-parse、拒绝 duplicate key/非有限 JSON 常量、exact-schema 校验并验证引用后装入 bundle；普通可变 Mapping 不得作为 capability 内部值。以下 digest 的定义互不替代：

| 字段 | 唯一含义 |
|---|---|
| `qualification_envelope_raw_sha256` | descriptor-root reader 取得的完整 outer envelope 原始字节摘要；绑定其中的 mode、scope 与所有 refs |
| `binding_admission_raw_sha256` / `binding_admission_canonical_json_sha256` | 完整 binding-admission 对象的原始字节摘要 / V12 固定 canonical JSON 字节摘要 |
| `evaluation_admission_raw_sha256` / `evaluation_admission_canonical_json_sha256` | 完整 normalized evaluation-admission 对象的原始字节摘要 / V12 固定 canonical JSON 字节摘要 |
| `evaluation_source_raw_sha256` | 原始 evaluator result 文件字节摘要，不是 admission envelope/projection |
| `evaluation_source_canonical_json_sha256` | strict parse 后依 V12 固定 canonical JSON 编码所得的 evaluator result 摘要 |
| `qualification_bundle_sha256` | 下述 domain-separated bundle 内容标识；不是 producer 身份或签名 |

固定 bundle 内容标识为：

```text
SHA256(
  ASCII("CORE-F4-QUALIFICATION-BUNDLE-V3") || 0x0a ||
  U64BE(len(envelope_raw)) || envelope_raw ||
  for role in [binding_admission, evaluation_admission, evaluation_source_raw]:
    U16BE(len(role_ascii)) || role_ascii ||
    bytes.fromhex(raw_sha256_hex) || bytes.fromhex(canonical_json_sha256_hex)
)
```

三个 referenced JSON object 的 canonical 摘要都在 strict parse 后，按 V12 固定 canonical JSON 编码派生；`raw_sha256_hex` 对 descriptor-read 原始 bytes 计算，`canonical_json_sha256_hex` 对相应 canonical bytes 计算；公式内均按 64 位小写 hex 解码为恰好 32 个 digest bytes（不是 ASCII hex 字符）。所有 raw 摘要对实际 descriptor-read bytes 计算，bundle 内为 immutable parsed value 加对应原始摘要，不保留可变 Mapping。每个 ref 的 schema、role、scope、revision、manifest、source/result digest 都必须交叉绑定；binding 与 evaluation admission 的 gate 投影字段逐字段相等。`VerifiedF4BatchDecisionInputV3` 与 `VerifiedF4BatchPreparationInputV3` 必须持有同一次验证产生的同一个 bundle capability 对象，且 `qualification_bundle_sha256` 相等；不得把一份 qualification 的 batch decision 与另一份 qualification 的 preparation/template 配对。

新 batch/preparation 产品使用 `qualification_bundle_sha256` 与 `qualification_envelope_raw_sha256` 两个不同字段：前者比较内容对象图标识，后者绑定实际 admission container 字节。旧 `qualification_receipt_sha256` 的 legacy 语义不得复用为 evaluation 子对象摘要；v1 tick wrapper 只可作 diagnostic 输入，不能发布 formal collection/preparation。新 collector 在 eligibility、case enumeration、audit/HDF5 读取之前，先复算 envelope/reference/bundle 一致性；字段缺失、来源拆分或任何 digest 层混用均 fail closed。

serialization-only golden vector（下列占位 JSON 不满足 qualification schema，仅测试哈希编码）固定如下。`envelope_raw` 为 ASCII `{"mode":"synthetic"}`，长度 20、hex `7b226d6f6465223a2273796e746865746963227d`；按角色顺序的 raw/canonical bytes 为 `binding_admission`=`{"a":1}` / hex `7b2261223a317d`、两种 SHA 均 `015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862`；`evaluation_admission`=`{"b":2}` / hex `7b2262223a327d`、两种 SHA 均 `0ab1a6d394cd30195f0642b67ae1180c375ffadf5dd7f39c390668b5fdb6da93`；`evaluation_source_raw`=`{"c":3}` / hex `7b2263223a337d`、两种 SHA 均 `caba9cb06ac77da7781b8bbd7e0700c58ea69bc7d8b12f0b6695a2af6ee6a6b3`。按 §1 公式（含 role 长度前缀及解码后的 32-byte digest）预期 `qualification_bundle_sha256=10c3a2d73f51262f595de744f111580157c4d37521c650a530cebe6e4142137e`。synthetic implementation 必须复算此向量，并单独断言 domain separator 的末尾是单个 `0x0a`，以防把 `0x5c 0x6e`、单个 `n` 或双 LF 误作同一编码。

## 2. dataset projection、同一文件对象与 launch barrier

V12 §2 的 case-audit capability 升版为 `VerifiedCaseAuditV2`，不得静默扩展 V1。它必须携带受信 producer 从该案例实际 HDF5 原始 bytes 流式读取所得的精确 `hdf5_size_bytes`（正整数文件长度）、`hdf5_sha256`、asset-relative source path、scope/recipe/lineage，以及私有 `snapshot_id`/FD capability。capability 同时固定 snapshot FD 的 `(st_dev,st_ino,mount_id,size,st_nlink)` identity 和 `FS_IOC_MEASURE_VERITY` measurement；size 与 SHA 必须从该**同一个已启用 fs-verity 的 FD** 读取计算，`st_nlink==1`。不把整个大型 HDF5 内容复制进 Python capability。sanitized projection 的 case `hdf5`/`sha256` 必须与该受信 audit 字段逐字节绑定，禁止只检查 SHA 字符串格式。`known_inputs_sha256` 仍须按 V12 规则由 descriptor-root 几何/控制资产重建 `KnownInputs` 后重新计算。

`hdf5_size_bytes` 的解析必须使用 exact builtin JSON integer 检查，要求 `>0` 且显式拒绝 bool；不能仅依赖会将 Python `bool` 当作 `int` 的宽松类型判断。

所有正式 asset 读取分两阶段：

1. planner 只能输出 `plan_ready=true` / `launch_allowed=false`。不得把文件名、正确 schema、audit 声明或尚未消费的 hash 单独提升为 `launch_allowed=true`。规划时不打开训练 HDF5 的旧策略可以保留，但此时只能生成未授权 job plan。
2. 唯一 trusted launch broker 在启动训练前，以仅 capability 可取得的 opaque `snapshot_id` 向 trusted snapshot supervisor 的 descriptor registry 取回该已注册 FD（如经 `SCM_RIGHTS`），不得按 caller path 重开或接受 caller 自选 handle。broker 必须在该 FD 上比较 `fstat` identity、`FS_IOC_MEASURE_VERITY` measurement、`hdf5_size_bytes` 与流式 raw SHA，全部等于 `VerifiedCaseAuditV2`；随后将同一 open-file-description FD 传给 worker。worker 的 HDF5 reader 必须从该 FD/file object 读取；reader 前后 `fstat` 与 verity measurement 不变，禁止校验后 `Path.resolve()`、`np.load(path)` 或 `h5py.File(path)` 重新按 pathname 打开。

可信 snapshot supervisor 必须从经过 audit 的源对象创建私有新 regular-file snapshot，完成写入与 `fsync` 后启用内核 fs-verity，并保存 `FS_IOC_MEASURE_VERITY` 的完整 measurement；启用后不得再写该 snapshot，且 descriptor registry 只返回其原 FD/dup，不能从路径解析替换对象。只有 `O_RDONLY`、重复 `fstat` 或 same-UID 约定不足以宣称不可变；若 filesystem/kernel 不支持 fs-verity、measurement 不匹配、registry 返回不同对象或 HDF5 library 不能从传入 FD/file object 读取，则 `launch_allowed=false`，不得退回 pathname reopen。snapshot hash producer、broker、worker 必须使用同一经注册 snapshot 对象；identity `(device,inode,mount_id,size,nlink)` 与 verity measurement 必须逐项相等，worker 读取前后 `(device,inode,size,mtime_ns,ctime_ns,nlink,mount_id)` 也必须不变。

正式 planner 与 worker 的测试至少分别证明：未知/错误 HDF5 hash 在 `plan_ready` 前拒绝；规划阶段从不输出 `launch_allowed=true`；launch broker 对内容不符/文件替换/不同 inode 或 mount 拒绝；成功路径由同一 FD 完成哈希和 HDF5 读取；reader 不会在验证后再次按路径打开。新增节点建议：

- `test_core_formal_planner.py::test_projection_hdf5_binding_requires_verified_case_audit`
- `test_core_formal_planner.py::test_planner_never_sets_launch_allowed`
- `test_core_formal_launch.py::test_worker_reads_same_verified_fd_without_path_reopen`
- `test_core_formal_launch.py::test_asset_replacement_between_plan_and_launch_is_rejected`
- `test_core_formal_launch.py::test_snapshot_registry_rejects_same_content_different_inode_or_mount`
- `test_core_formal_launch.py::test_snapshot_fd_must_match_pinned_verity_measurement`

这些节点均只允许 `tmp_path`/内存 synthetic assets，不调用实际 planner job writer、scheduler、training 或生产 HDF5。worker 真正启动仍须另行满足计划中的资源/正式准入门；本草案不开放该门。

## 3. 信任及迁移边界

FD、mount 与 content digest 是对象完整性机制，不是 producer 身份、运行时加载代码身份或 supervisor 诚实性的证明。Python 内部 capability 也不抵御同进程恶意反射；consumer 必须由未来固定 launcher 建立运行时/导入身份闭包。新 capability-only API 实现前，所有既有 collector、F4 `batch_decision()` / `prepare_production_batch()`、formal planner/worker 及 `core_dataset` mapping/path reader 只能用于 diagnostic；旧 `CoreDataset.formal_eligible` 即使为 true 也不得被任何 formal consumer 当作资格、`plan_ready` 或 `launch_allowed`。旧 public mutation/preparation ingress 必须在读取 caller gate 字段、导入执行器或创建输出前拒绝，不能 fallback 到 Mapping/path；新 versioned verifier 必须唯一 mint dataset/qualification capabilities 并经 descriptor-root consumer 消费。V13 不能将 v1 collector、当前 planner `launch_allowed` 或任一 one-shot receipt 升级；正式 ingress 必须先由新的 versioned public API 实现并通过独立审查。
