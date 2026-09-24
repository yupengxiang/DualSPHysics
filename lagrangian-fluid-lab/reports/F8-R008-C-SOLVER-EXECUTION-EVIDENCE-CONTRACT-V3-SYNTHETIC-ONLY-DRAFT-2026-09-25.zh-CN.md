# F8 R008 C 阶段 execution-evidence synthetic schema v3（草案）

状态：Terra (`gpt-5.6-terra`, high) v2 follow-up `REVISE` 后的修订候选，待只读复审。本文只提议一个 **synthetic-only diagnostic schema**，不是 production execution schema；其唯一 gate 输出恒为 `open`。旧 C v1、v2 草案与所有冻结 R008 输入均不改写；不授权或启动 solver/native/GenCase/worker/GPU/queue。

## 1. v2 follow-up findings 与 v3 限定目标

v2 把信任边界和 fail-closed 条件补全了一层，但 Terra follow-up 发现：跨阶段 `../B/receipt.json` 被“禁止 `..`”误伤；复杂对象仍缺 exact sub-schema；证据 manifest 有自引用风险；synthetic fixture 尚未被机器锁死为 `open`；scope/qualification row digest 未直接绑定；`accinput` 时间窗被误写成全局量；solver 与 supervisor 的 cgroup 归属不明确。

v3 仅解决**静态解析接口与无权威输出**的设计问题。它不宣称当前能采集可信 runtime evidence，也不冻结 production trust root、source-to-binary 或完整 solver call graph。

## 2. 文件对象图与无循环绑定

每个 C attempt 继续保留既有对象：

1. C-v1 `receipt.json` 绑定 C raw-output manifest；该 manifest 仅包含 solver 的 native frames 和已登记 solver logs，按 C-v1 schema 产生。
2. C-execution v3 的 `evidence.json` 是 detached sidecar。它的签名 payload 绑定 C-v1 receipt、raw manifest、B receipt、authorization、scope、qualification row，以及所有 supervisor journals 的 bytes/SHA-256；payload 不含 `evidence.json` 自身的 digest。
3. `execution-index.json`（若生成）只是非权威导航索引，不被签名、不被 verifier 当证据；verifier 直接按 payload 中的 stage-role/object-id 从调用方传入的只读 root FD 解析对象并复算摘要。
4. C-v1 raw-output manifest 永不列出 detached sidecar/journals；sidecar 也不绑定 `execution-index.json`。因此对象图无 hash cycle；删除/篡改 index 不得改变验证结果。

## 3. 跨阶段引用：stage FD + digest，不传路径

所有 v3 引用对象使用同一个 exact-field 结构，不出现 host path 或 `../`：

| 字段 | 类型/规则 |
|---|---|
| `stage` | enum：`prelaunch`, `scope`, `qualification`, `B`, `C`, `runtime`, `build`, `trust` |
| `role` | enum：`authorization`, `scope_receipt`, `qualification_row`, `b_receipt`, `c_v1_receipt`, `raw_manifest`, `runtime_image`, `case_snapshot`, `build_attestation`, `trust_bundle`, `process_journal`, `input_journal`, `termination_journal`, `resource_journal`, `solver_log` |
| `object_id` | 1–64 ASCII `[a-z0-9][a-z0-9._-]*`，不得是路径、`.`/`..` 或含 `/`、反斜线、NUL |
| `bytes` | JSON integer，`1..1073741824` |
| `sha256` | 64 个小写十六进制字符 |

resolver 收到独立的 stage-root directory FD map；按冻结 `(stage, role, object_id)` allowlist 做 descriptor-relative/no-follow 查找，校验普通文件、`st_nlink==1`、bytes、SHA-256 和 mount identity。C-v1 receipt 内既有 `../B/receipt.json` 只按 legacy data 读取，不用于文件打开；v3 的 `b_receipt` reference 以 B root FD 重新解析，并要求其摘要与 C-v1 receipt 的 materialization binding 完全相等。

## 4. Signed envelope 与编码约定

`evidence.json` 外层 exact-field 为 `{schema,payload,signature}`；`schema` 固定 `core.cfd.f8.r008_c_execution_evidence.synthetic.v3`。`signature` exact-field 为 `{algorithm,key_id_sha256,signature_base64}`。`payload` 仅允许 §5 列出的字段，所有 object 均 `additionalProperties=false`、必需字段齐全；拒绝 duplicate JSON key、非 I-JSON、未知字段、NUL、NaN/Infinity 和超界对象。

JCS 与 Ed25519 编码候选沿用 v2：RFC 8785 canonical UTF-8 payload，由 RFC 8032 Ed25519 对 `ASCII("F8-R008-C-EXEC-SYNTHETIC-V3\n") || JCS(payload)` 签名。所有 binary64 时间值用 IEEE-754 bits 的 16-char lowercase hex 字符串；所有可能超过 JS safe-integer 的 `uint64`/单调时钟用固定 16-char lowercase hex 字符串，禁止把它们当 JSON number。bytes、PID、有限上限内 sequence 等小整数才用 JSON integer。

synthetic key 只用临时 fixture 生成，且它的存在不构成 trust bundle。synthetic verifier 必须无条件输出 §8 定义的 `open` diagnostic；不得返回 `defined_pass`/`defined_fail`，不得写 gate registry 或 qualification receipt。

## 5. Payload exact-field 候选

Payload 顶层字段恰为：

`payload_schema`, `mode`, `nonce_hex`, `scope_binding`, `qualification_row_binding`, `authorization_binding`, `b_receipt_binding`, `c_v1_receipt_binding`, `raw_manifest_binding`, `supervisor_identity`, `trust_policy_binding`, `host_identity`, `namespace_identity`, `runtime_image_binding`, `input_snapshot_binding`, `build_provenance_binding`, `invocation`, `configuration_audit`, `control_horizon_audit`, `process_journal_binding`, `input_journal_binding`, `termination_journal_binding`, `resource_journal_binding`, `cgroup_snapshot`, `terminal_state`, `log_bindings`, `started_monotonic_ns_hex`, `ended_monotonic_ns_hex`。

固定子对象：

| 对象 | Exact fields |
|---|---|
| `supervisor_identity` | `supervisor_id`, `version`, `executable_sha256`, `source_manifest_sha256`, `measurement_backend_id`, `measurement_backend_sha256`, `uid`, `signer_key_id_sha256` |
| `trust_policy_binding` | 上述 §3 ref fields，且 `stage=trust`, `role=trust_bundle`；信任 pin 必须另由 verifier 的 out-of-band activation input 提供 |
| `host_identity` | `boot_id_sha256`, `kernel_release`, `architecture`, `runtime_root_sha256` |
| `namespace_identity` | `pidns_inode_hex`, `mntns_inode_hex`, `userns_inode_hex`, `solver_cgroup_id`, `supervisor_cgroup_id`；后两者必须不同 |
| `runtime_image_binding` | §3 ref fields，且 `role=runtime_image` |
| `input_snapshot_binding` | `snapshot_id`, `tree_sha256`, `mount_id_hex`, `namespace_inode_hex`, `read_only`, `opened_before_ns_hex`, `closed_after_ns_hex`, `inventory_binding` |
| `build_provenance_binding` | §3 ref fields，且 `role=build_attestation` |
| `process_journal_binding` / `input_journal_binding` / `termination_journal_binding` / `resource_journal_binding` | §3 ref fields，并分别限定对应 role |

`invocation` exact fields：`argv_utf8` (1–256 strings, total UTF-8 bytes ≤1 MiB), `argv_sha256`, `cwd_object_id`, `environment` (≤256 `{name,value}` entries, total ≤64 KiB, unique names), `executable_binding`, `wrapper_binding` (ref or null), `exec_monotonic_ns_hex`, `pid`, `ppid` (integer or null)。没有 shell expansion；未知 env 项由 allowlist 拒绝。

`configuration_audit` exact fields：`source_tree_sha256`, `parser_manifest_binding`, `grammar_revision`, `feature_set` (unique enum strings), `normalized_config_sha256`, `opt_bindings` (ref array, ≤10; R008 synthetic profile 默认必须为空), `external_config_bindings`, `generated_xml_binding`, `accinputs`。`accinputs` 必须逐 runtime input entry 记录，不是全局标量：每项 exact fields 为 `input_index`, `xml_element_ordinal`, `expanded_mk_first`, `expanded_mk_last`, `enabled`, `time_ini_ieee754_hex`, `time_end_ieee754_hex`, `table_first_time_ieee754_hex`, `table_last_time_ieee754_hex`, `table_binding`。顺序/数量必须与解析后的 `JDsAccInput::Inputs` 一致；`TimeIni/TimeEnd` 是每个 `<accinput>` 经 range expansion 后的 input 属性，缺项、重复、默认值无法解释或 table endpoint 未绑定均为 `open`。

`control_horizon_audit` exact fields：`scope_digest`, `qualification_row_digest`, `t_end_ieee754_hex`, `source_callgraph_binding`, `query_site_ids` (unique sorted IDs), `effective_time_max_ieee754_hex`, `control_table_end_ieee754_hex`, `strict_query_bound`, `time_comparison`。其中 `strict_query_bound` 固定 `0 <= t_query < effective_TimeMax <= min(T_end,control_table_end)`，`time_comparison` 固定 `binary64_numeric_strict_no_tolerance`。当前 call graph 未闭合时不可签出可 pass payload。

`cgroup_snapshot` exact fields：`cgroup_version` 固定 2、`mount_id_hex`, `solver_cgroup_id`, `supervisor_cgroup_id`, `limits`, `cpu_stat`, `memory_peak_bytes`, `memory_events`, `pids_events`, `io_stat`, `pressure_events`, `membership_journal_binding`, `populated_after_reap`。必须满足 solver/supervisor cgroup 不同且 solver `populated_after_reap=false`；签名/sidecar flush 由 solver cgroup 外的 supervisor 完成。

`terminal_state` exact fields：`exit_code`, `signal`, `timed_out`, `all_children_reaped`, `normal_time_limit_reached`, `nsteps_break`, `minimum_fluid_stop`, `terminate_seen`。这些字段是待 journal 验证的陈述，不可由 sidecar 布尔值自证。

`log_bindings` 为 ≤64 个 ref objects；每项另带 `parser_id`, `parser_sha256`, `parse_status`，固定 parser 版本并拒绝未知语法。日志只能辅助核验，不作为 process/horizon/trust 证明的根。

## 6. Journal / trust / build 子格式

- 每个 journal 顶层 exact fields：`schema`, `attempt_nonce_hex`, `source_id`, `source_binary_sha256`, `coverage_start_ns_hex`, `coverage_end_ns_hex`, `event_count`, `overflow`, `events`。要求 nonce 与 payload 相同、sequence 连续、`overflow=false`、起止覆盖 exec 前核验至 solver descendants 全 reaped；超过 v2 的固定条数/字节上限或任何 lost event 即 `open`。
- process event exact union：`exec={seq,mono_ns_hex,kind,pid,ppid,executable_binding,argv_sha256,cwd_object_id,environment_sha256}`；`fork={seq,mono_ns_hex,kind,pid,ppid}`；`exit={seq,mono_ns_hex,kind,pid,exit_code,signal}`；`reap={seq,mono_ns_hex,kind,pid}`；`load={seq,mono_ns_hex,kind,pid,object_binding,object_kind}`；`cgroup={seq,mono_ns_hex,kind,pid,action,cgroup_id}`。每一分支只允许列出的字段。
- input event exact union：`mount={seq,mono_ns_hex,kind,mount_id_hex,object_binding,read_only}`；`open={seq,mono_ns_hex,kind,pid,object_binding,operation,result}`；`deny={seq,mono_ns_hex,kind,pid,requested_root,reason}`。未知 root 成功读取、未登记 mount 或无法解释的路径解析均 fail-closed。
- termination event exact union：`initial={seq,mono_ns_hex,kind,dirout_binding,terminate_present}`；`fs_event={seq,mono_ns_hex,kind,dirout_binding,operation,object_name,actor_pid,result}`；`coverage={seq,mono_ns_hex,kind,monitor_started,monitor_ended,lost_count,overflow}`。实际 `DirOut` 必须解析为唯一绑定 mount；exec 前 `TERMINATE` 必须不存在，任何 create/write/rename/unlink 或监控丢失均不能 pass。
- trust bundle 顶层 exact fields：`schema`, `bundle_id`, `version`, `keys`；每个 key exact fields：`key_id_sha256`, `public_key_base64`, `role` (`supervisor|builder`), `not_before_utc`, `not_after_utc`, `revoked_at_utc` (string or null)。bundle digest 必须由独立、执行前固定的 activation root 提供；bundle 内自签/自 pin 不可信。
- builder attestation 顶层 exact fields：`schema`, `builder_id`, `source_tree_sha256`, `source_manifest_binding`, `clean_worktree`, `build_script_binding`, `toolchain_bindings`, `build_flags_sha256`, `build_command_sha256`, `artifact_bindings`, `rebuild_result`, `signer_key_id_sha256`, `signature`。`artifact_bindings` 逐项覆盖主程序、CPU/GPU device image、全部动态库；`rebuild_result` 仅允许独立重建 hash 相同或受信 builder attestation。source commit/hash 本身不是 build proof。

上述 schema 仅规定字段/边界，不表示当前主机存在能够诚实采集这些 event、snapshot、build 或 trust facts 的实现。

## 7. Admission / version activation

C-v1 receipt/verifier 永久保持结构兼容：`solver_execution={}` 或 C-v1 `status=passed` 不得映射 execution gate。未来生产 activation 必须是单独的、执行前固定的 root-authorized object，exact fields：`schema`, `mode`, `scope_digest`, `qualification_table_digest`, `c_v1_schema_sha256`, `c_execution_schema_sha256`, `verifier_sha256`, `supervisor_trust_bundle_sha256`, `builder_trust_bundle_sha256`, `allowed_profile_sha256`, `signer_key_id_sha256`, `signature`。缺失/无效时没有 production gate consumer。

synthetic-only parser 不消费 production activation，也不调用/写入 gate registry。对任何合法、非法或伪造的 synthetic fixture，它只能返回：`diagnostic_schema`, `payload_shape_valid`, `signature_diagnostic`, `gate_state="open"`, `qualification_credit=0`, `registry_write=false`, `mode="synthetic_only"`。这条规则由调用方 API 与输出 schema 双重常量化；测试必须证明即使 fixture key 自签且字段齐全也不产生 pass。

## 8. 当前 source / host closure 状态

现有 C-v1 verifier 只校验 raw manifest/full-axis 与输出文件绑定；其 synthetic fixture 的 `solver_execution={}` 仍可通过结构验证。`JSphCpu.cpp`/`JSphGpu.cpp` 的直接调用点与 `JDsAccInput.cpp` 的查询点已定位，但完整 source/build/feature-bound call graph 尚未审计。`JDsAccInput::ReadXml` 将每个 active `<accinput>` 的 `time.start` 默认设为 0、`time.end` 默认 `DBL_MAX`，并可能把单个 MK range 展开为多个 `Inputs` entry；因此 v3 必须逐 entry 核对。

当前无受信 supervisor/event source、out-of-band trust anchor、builder attestation、完整 input snapshot producer 或 solver source-to-binary closure。当前只能审查/实现 synthetic-only shape parser；真实 runtime gate 必须保持 `open`，不得以 rootless bwrap、OpenSSL/Ed25519 可用、日志或 C-v1 `passed` 替代信任闭环。

## 9. 复审通过前禁止项

在 Terra High 复核确认 §2–7 的 exact schema、对象解析、无循环签名、synthetic 永远 open 和 cgroup 分离语义前，不实现 verifier、不变更 C-v1、不写 gate registry。复核通过也只解锁 synthetic-only parser/negative tests，不解锁真实 execution evidence、solver、worker 或 T1 qualification。
