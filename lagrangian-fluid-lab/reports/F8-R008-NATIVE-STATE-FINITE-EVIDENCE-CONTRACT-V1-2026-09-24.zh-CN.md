# F8 R008 native-state finite evidence contract v1

状态：静态设计提案；Terra High（`gpt-5.6-terra`, high；agent `01a0d376-e477-7ab0-be6e-55325dc9de10`）当前版本只读复审 `PASS`。它只定义对已闭合 B/C/D + table-v2 结果生成的逐帧有限值证据；不实现 verifier，不给 native-integrity gate、T1 或资格信用。

## 1. 目的与边界

现有 table-v2 verifier 逐帧验证完整原始 ID 轴，再投影到 B 阶段冻结的 fluid ID，并检查 fluid-only 的 `Pos[d]`、`Vel`、`Rhop`、mass 与完整时间轴。它没有对 non-fluid ID 的状态数值做 finite 检查。因此“表语义等价”不能替代 native-state integrity。

本合同只补充可被现有冻结格式支持的证据：对每个原始 solver BI4 帧的全部 `Pos` 或 `Posd`、`Vel`、`Rhop` 标量组件逐块检查 finite 值，同时重新绑定其原始数组描述符/字节哈希与 D safe-decode receipt。non-fluid 粒子同样纳入这三个数组的 finite 统计。它不是最终完整性裁决器。

每次收集必须从调用方信任字节重新验证 B/C/D provenance 与 native-fluid-table-v2 semantic chain；不得接受 `verified=true` 一类可伪造的摘要替代。冻结 scope 固定有 15 个资格案例；单次收集只绑定其中恰好一个 `qualification_only=true` case，不能把 15-case 分母缩成单例，也不能接纳 32 个 production rows。必须要求 C/D 覆盖该案例完整 `t=0..TimeMax` 原生轴。

实现必须在单次收集中持有 B/C/D bundle-root 与各 stage output root 的目录 FD，并通过 FD-preserving verifier core 使用同一组 roots；只收路径的既有入口本身不满足一致快照要求。持有 table FD 至结束。每帧 C 文件均在 held C output FD 下 no-follow 打开，验证 single-link regular-file、声明的 size/SHA，扫描前后重核 descriptor 身份与 SHA。raw-array 描述符、数据哈希及 XML、安全解码数组/文件哈希须与该帧的 D receipt 和 outputs manifest 精确相符。开始与结束时均须验证 B/C/D 三个 stage receipt 的 `status == "passed"`、重新校验完整 provenance-chain 和 table-v2 semantic chain，并从 held roots 重读、核对所有参与绑定的 B/C/D receipts、manifests、B cohort/input 文件、C frames、D safe-decode outputs 和 table 的 descriptor identity、字节数与 SHA。任一状态非 `passed`、绑定字节变化、FD 身份变化或复核失败即 fail-closed，不发布 evidence。顶层 bindings 必须对应这组 post-scan 未变的字节；仅检查可变路径当前指向的文件不满足本合同。

输出须绑定本次校验所用的 B/C/D authorization SHA-256、独立 code-review receipt SHA-256、table/schema review receipt SHA-256、metric review receipt SHA-256，以及 runtime assumption 的规范化摘要。它们只标识调用方提供的信任上下文；不表示授权签名真实性、review 来源真实性、loaded-module identity 或 runtime 已被独立认证。

这条实现链与被检查的 safe BI4 scanner/parser 同源，不是 decoder-diverse 复核；也不能认证 solver binary、历史 native decoder build、授权签名、loaded-module identity 或 runtime。此类来源限制继续作为外部信任边界记录。

## 2. 输出 schema

新输出独立于冻结 D v1 bundle，不能向其 `outputs/` 或 manifests 追加文件；使用独立目录内的 no-follow、single-link 临时普通文件，经 fsync 后以 no-replace 原子发布，不覆盖已存在 evidence。下面代码块列出固定常量字段，不是完整 JSON 样例：

```text
schema: core.cfd.f8.r008_native_state_finite_evidence.v1
status: partial_native_state_evidence_not_adjudicated
native_integrity_gate_status: open_not_adjudicated
native_integrity_evaluated: false
T1_numerical: false
readiness_pass: false
qualification_credit: 0
table_semantics_status: passed
```

顶层绑定 `scope_id`、唯一 `case_id`、B/C/D receipt/manifest SHA、table-v2 SHA、上述信任上下文摘要、完整帧数及每帧序号/冻结与观察时间。`frames` 必须逐 ordinal 完整对应 C manifest 和 D decoded-frame manifest；须保留完整 native axis 及 observation-window membership，不得裁切失败帧或只报告 observation window。

JSON 结构按 exact field-set 冻结：顶层字段恰为 `schema`、`status`、`native_state_finite_status`、`native_integrity_gate_status`、`native_integrity_evaluated`、`T1_numerical`、`readiness_pass`、`qualification_credit`、`scope_id`、`case_id`、`stage_statuses`、`table_semantics_status`、`bundle_bindings`、`trust_context`、`qualification_scope`、`frames`。常量值为 schema/status 字符串如上、`native_integrity_gate_status="open_not_adjudicated"`、`native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、`qualification_credit=0`、`table_semantics_status="passed"`。`stage_statuses` 恰含 B/C/D 且全为 `passed`；`bundle_bindings` 恰含 B/C/D，每项含 `receipt_bytes`、`receipt_sha256`、`manifest_bytes`、`manifest_sha256`；D 另含 `decoded_frame_manifest_bytes`、`decoded_frame_manifest_sha256`、`table_bytes`、`table_sha256`。`trust_context` exact fields 为 `authorization_sha256`（恰含 B/C/D）、`code_review_receipt_sha256`、`table_review_receipt_sha256`、`metric_review_receipt_sha256`、`runtime_assumption_sha256`。`qualification_scope` exact fields 为 `qualification_only`、`qualification_row_count`、`full_frame_count`、`observation_window_start_ordinal`、`observation_window_end_ordinal`；其前两项固定为 `true` 与 `15`。frame、array 子对象采用本报告逐项定义的字段，不允许额外字段。所有整数须为 JSON integer（不能是 bool），所有开关须为 JSON boolean，unknown/missing/duplicate fields 一律拒绝；JSON 仅允许整数数值，不序列化十进制浮点数。字节格式固定为 UTF-8、无 BOM、排序键、紧凑分隔符、`ensure_ascii=false`、`allow_nan=false`，末尾单个 LF；解析端拒绝重复 key、NaN/Infinity 常量及非 canonical 表示。

每个 frame 的 exact fields 为 `ordinal`、`expected_time_s_ieee754_hex`、`observed_time_s_ieee754_hex`、`observation_window_member`、`native_arrays`。两个 time 字段都必须是有限、canonical binary64 hex，观察值从原始 `TimeStep` 解析，并与 frozen axis 精确同位相等；拒绝负零。每项 array 的 exact fields 为 `array_name`、`type_code`、`dtype`、`shape`、`particle_count`、`scalar_component_count`、`raw_array_sha256`、`finite_count`、`nan_count`、`positive_infinity_count`、`negative_infinity_count`、`minimum_finite_source_bits_le_hex`、`minimum_finite_component_ordinal`、`maximum_finite_source_bits_le_hex`、`maximum_finite_component_ordinal`、`required_state_values_finite`。component ordinal 为该数组原生 row-major scalar 序从 0 开始的索引。`native_state_finite_status` 仅表示数值观察（`observed_finite` / `observed_nonfinite`）；`native_integrity_gate_status` 固定为 `open_not_adjudicated`。`status` 固定为 `partial_native_state_evidence_not_adjudicated`；任一输入信任、schema、provenance 或一致快照检查失败时不生成此文档。

类型/长度约束同时属于 schema：所有 SHA-256 为 64 个小写十六进制字符；`case_id` 必须精确匹配冻结 15-case 列表之一，`scope_id` 精确等于冻结值。`frames` 是非空 object array，长度等于该 frozen row 完整 expected axis（1..1497）；按 ordinal 0..N-1 连续排序。每帧 `native_arrays` 为恰好 3 个 object，顺序固定为 position（`Pos` 或 `Posd`）、`Vel`、`Rhop`。`CaseNp`/`particle_count` 必须为 1..10752 的 JSON integer；shape 是由 JSON integer 组成的列表，scalar count 与 shape 精确一致且不超过 32256。位置映射为 `Pos:(type_code=22,dtype="<f4",shape=[N,3])` 或 `Posd:(23,"<f8",[N,3])`；`Vel:(22,"<f4",[N,3])`；`Rhop:(11,"<f4",[N])`。这里 `dtype` 定义为 canonical NumPy scalar dtype，不复用 safe scanner manifest 中的 struct-format `"<fff"`/`"<ddd"`。各 name/dtype/type/shape 均为 JSON string/integer/list 的相应精确类型，不能用 bool 代替 integer。每数组四种值计数均为 JSON integer 且在 0..scalar count 内，和精确等于 scalar count；finite extrema bits 长度分别为 8/16 个小写 hex 字符，ordinal 为 0..scalar count-1，解码值必须有限并等于该 ordinal 的原始值；无 finite 值时 extrema 和 ordinal 均为 null。receipt/manifest 字节数为 1..8 MiB、raw BI4 为 1..64 MiB、table 为 1..2 GiB，均须与 held FD 的精确 size 相等；证据 JSON 自身不超过 64 MiB。原生 required-array 单项最多 258048 bytes；其余输入字节及字段还须满足对应已冻结 verifier 的更严格上限。`qualification_scope` 的 observation-window 首末 ordinal 必须等于冻结 row，且满足 `0 <= start <= end < full_frame_count`；每帧 `observation_window_member` 精确等于 `start <= ordinal <= end`。frame 的 expected time 必须与 frozen axis 同 ordinal 值相等。

每帧 `native_arrays` 固定包含恰好一个 `Pos`/`Posd`、一个 `Vel`、一个 `Rhop`。四者 count 必须与 B 生成 XML 的 `CaseNp` 相符，shape/dtype/type_code 映射与上述 exact schema 一致。扫描应对原始 little-endian 字节流分块处理，不得先整体物化数组或把 `Posd` 提升/转换到另一精度；同一遍扫描应重算并比对 descriptor 对应的 raw-array SHA-256。`minimum_finite_source_bits_le_hex` 与 `maximum_finite_source_bits_le_hex` 是按 IEEE 数值比较选出的原生 dtype 位模式；相同数值（包括 `-0/+0`）以 row-major 标量序中最早的 component ordinal 决胜，并同时输出相应 ordinal。没有有限值时 extrema bits 和 ordinal 均为 JSON `null`。f32/f64 bits 分别固定为 8/16 个小写十六进制字符（对应 4/8 个 little-endian 原始字节）；输出禁止 NaN/Infinity JSON 数值。

支持的最小 native 字段按已审 BI4 格式约束为：`Idp:uint32`、恰一个 `Pos:float3` / `Posd:double3`、`Vel:float3`、`Rhop:float`；四者 count 必须与 B 生成 XML 的 `CaseNp` 相符。所有其他扩展数组继续由现有完整递归 manifest 精确绑定，但不在本次 finite-state 结果中冒称已做物理完整性检查。

每个 array 的 `required_state_values_finite` 等于 `finite_count == scalar_component_count`。顶层 `native_state_finite_status` 在全部帧的全部 required arrays 均有限时为 `observed_finite`，任一值非有限时为 `observed_nonfinite`；`native_integrity_gate_status` 固定为 `open_not_adjudicated`，因为有限值观察不构成完整 integrity adjudication。不得输出 `required_state_values_finite_observed`、`native_integrity_passed`、`gate_pass` 或 T1 结论。任何 non-finite 值是可报告的科学负证据，不应通过删除 frame 或改分母消失。

## 3. 已冻结事实与明确开放项

本设计文档引用以下已冻结常数，但不得借它们单独生成 native-integrity PASS：density `[950,1050] kg/m³`、Mach 上限 `0.0010125`、wall penetration 上限 `0.001875 m`、excluded-fluid 数为 `0`，以及 `particle_overlap=false`。现有 verifier/table chain 还可给出完整 ID/cadence/TimeStep 绑定与每帧 `MassFluid` 对 B 初始 binary64 的精确位相等证据。

本设计报告静态记录上述已有阈值（`frozen_threshold_present_but_not_adjudicated`）和无冻结算法的开放项（`open_not_adjudicated`）；v1 finite-evidence JSON 不复制物理阈值或添加其状态字段。不得自行定义：density interval 是否作用于 non-fluid ID、post-run Mach estimator、总质量公式/容差、particle-wise wall 处理和 penetration 计算方法、overlap 判据、`BoundNor` 覆盖率/质量阈值，或最终 15-case native-integrity 聚合规则。完整三周期窗/no-extrapolation 由既有 observation-window 与 B/control 合同分别供证；finite-evidence 输出绑定 frozen case 和完整原始时间轴，但不替代或声称通过这些独立 gate。

## 4. 测试与安全约束

正负例仅用临时合成 BI4。必须证明：fluid-only table-v2 在 non-fluid state 含 NaN/Inf 时仍可能语义通过，而本 evidence output 会定位并报告相应 raw state 非有限值；Pos float32 与 Posd float64 均保留原生 dtype/位模式；D safe-decode array manifest 与 C raw descriptor 不一致时 fail-closed；raw FD 在扫描中被截断/替换时拒绝；不支持的数组类型、错误 count、重复/缺失 required array 均拒绝。

无论 finite 扫描结果如何，输出强制 `native_integrity_evaluated=false`、`T1_numerical=false`、`readiness_pass=false`、资格信用 0。此次设计或之后的合成实现均不授权 production bundle/solver frame 读取、GenCase、native decoder、solver、worker、GPU 或 queue。
