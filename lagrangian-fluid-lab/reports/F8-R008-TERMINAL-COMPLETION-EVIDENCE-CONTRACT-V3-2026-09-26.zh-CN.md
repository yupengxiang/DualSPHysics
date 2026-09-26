# F8 R008 terminal completion and artifact-visibility evidence contract v3

状态：只读设计修订，待独立复核。v3 additive supersede v2；v1/v2 文档与各自 review history 原样保留。它不实现 verifier、不增加 gate、不修改 frozen scope/registry/分母/权限，不读生产数据，不执行 GenCase/native decoder/solver/worker/GPU/queue。v3 仅定义未来受信 attempt 应如何证明最后已应用 CPU timestep 的 SaveData 调用路径完成、且退出后 artifacts 当前可重新打开并复验；**不声称 fsync/断电持久化**，不认证当前不存在的 worker/key，也不授予资格信用。

## 1. v1 复核 findings 与关键修正

只读技术复核结论 `REVISE`（审阅者未 attestate 模型身份，不记模型签核）：

- **P1 fresh-run false pass：** `PartIni=0`、`TimeStepIni=0` 不足以证明 fresh run。官方 OPT 支持 `PARTBEGIN:12:0:<dir>`；内部 `PartIni=PartBeginFirst=0`、`TimeStepIni=0`，但粒子仍由旧 `PART_0012` 加载。v2 因此要求无 `PARTBEGIN`/restart source，并绑定冻结 initial-state bytes 与实际加载来源。
- **P2 receipt 语义不够 machine-exact：** v1 只列了字段分组，未冻结所有 exact keys/types、canonical receipt bytes、signature payload bytes 与 RunPARTs 时间文本算法。v2 固定 exact-field schema、类型/边界、canonical JSON 和 domain-separated Ed25519 payload；RunPARTs 时间文本须逐字等于固定官方 `RealStr(double,16,true)` 在冻结 CSV/runtime locale 下的结果，不能临时换用未证明等价的数值容差或格式器。
- **P3 “flush”措辞超出源码保证：** CSV writer 在写入时 `flush()` 并检查 stream error；BI4 `SaveFile()` 写后检查 stream 状态并关闭，但没有 `fsync`，也没有检查 close 后的错误。故 v2 只声称正常进程内写入路径完成且退出后重新打开的 artifact bytes 当前可见、可解析并可 hash；不声称抗断电/内核崩溃持久性。若后处理 reopen/parse/hash 失败，即使 solver exit 0 也不闭合。



### v2 复核 findings 与 v3 修订

v2 经 Terra High 模型配置的只读复核结论为 `REVISE`；平台未提供模型身份 attestation，不记为已认证 Terra High 签核。没有 P0；复核肯定 v2 修正了 PARTBEGIN fresh-run、最终保存/文件可见性、掉电 durability 与资格中立边界。新增 findings：

- **P1 OPT/argv 来源映射：** v2 未冻结 `-opt` 到实际被打开 OPT inode/hash 的映射、parser profile、相对路径基准。v3 禁止 R008 argv 中全部 OPT options、要求 `opt_sources=[]`，并固定 argv 单 token profile；trusted input-access trace 绑定实际读取的 Definition/control/初始状态文件至 manifest。
- **P2 TMAX:0：** 源码允许零值，但只在最终 `cfg->TimeMax>0` 时覆盖 Definition。v3 逐 token 重算并区分 override 出现与生效：最后值为零表示未覆盖，Definition 必须自行等于冻结 T_end。
- **P2 locale：** v2 的 `csv_numeric_locale="C"` 是未认证自述。v3 要求 supervisor 签名的 runtime environment receipt 绑定 exec locale C，并由固定 binary/source/runtime closure 排除后续 locale mutation。
- **P3 外部引用：** v2 未明确 build/inventory/trust registry schema/hash。v3 新增固定 schema IDs、canonical payload SHA pins 与 fail-closed verification order；这些信任工件当前不存在，receipt 保持不可验证。

## 2. 固定适用域与 fresh-run 证明

适用域仅为 frozen R008 的 CPU single-piece、一个 solver process、一个 attempt、一个独占 output writer；不接受 GPU、多-piece、restart、append、resume、任何 `OPT` source 或 output namespace 重用。必须绑定 frozen `Definition/control` pack、GenCase initial-state bytes/manifest、准确的 case directory identity、原始 argv 与 solver/build/runtime identity；`opt_sources` 必须为空。

fresh-run 不由 caller 的 `fresh=true` 或 `PartIni=0` 声明推导。消费端按 source-pinned v5.4 parser 从原始 argv 重算，要求没有 `PARTBEGIN`/restart/append，且全部 `OPT` options 缺席。由可信 input-access trace 证明实际 `LoadParticles` 输入与冻结 GenCase initial-state manifest 精确同源，SHA/dev/ino 验证通过；任何 source/access trace 缺失、来源不符或目录重绑定均 `missing/open`。

有效 `TimeMax` 必须依 source-pinned v5.4 precedence 从 Definition 与 argv 重算并 binary64 精确等于 frozen `T_end`。最后一个 `TMAX` token 为正时它必须 bitwise 等于 `T_end`；未出现或最后为零时 Definition 必须等于 `T_end`，因为源码仅在 `cfg->TimeMax>0` 时覆盖。`NSTEPS` 必须 absent/zero，`SVSTEPS` 必须 absent/false。其余 output cadence、`SDAT_Info`、`SDAT_Binx`、`DataOutBi4` 均须按 frozen contract 逐项重算。

## 3. receipt v3 exact wire schema

### 3.1 Raw bytes 与类型规则

整个 receipt 是 UTF-8 JSON，最多 64 MiB、最大嵌套深度 8；拒绝 BOM、无效 UTF-8、重复 key、未知/缺失字段、NaN/Infinity、JSON float 数值、非规范十进制整数及超限数组。解码后每个 JSON string 都须为可打印 ASCII；所有 binary64 时间以 canonical lowercase Python `float.hex()` string 表示，并须 round-trip `float.fromhex(s).hex()==s`；SHA-256 是恰 64 个小写 hex 字符。路径是 ASCII、相对于指定 root 的 POSIX 相对路径，1–1024 bytes；不允许绝对路径、`.`/`..`、空分量、NUL、反斜线或重复路径。整型字段必须是 JSON 整数 token（实现须用 `type(value) is int` 等价检查，拒绝 bool），且逐字段执行下表边界。JSON bytes 必须精确等于：

```text
json.dumps(object, ensure_ascii=False, sort_keys=True,
           separators=(",", ":"), allow_nan=False).encode("utf-8")
```

不带 BOM、前缀/尾随空白或 final newline。任何字段编码、key 排序或序列化差异均拒绝。

### 3.2 Top-level exact fields 与 nested fields

根对象恰含 `schema, identity, dependency_pins, solver, invocation, process, namespace_root, input_root, output_root, input_access, termination_watch, artifacts, attestation`；`schema` 固定为 `core.cfd.f8.r008_terminal_completion_evidence.v3`。禁止 caller-authored derived status/pass/complete/flush 字段。路径锚点固定：namespace/input/output/CWD 相对受信 supervisor registry 打开的 namespace root；`source_hashes.path` 相对 `solver.source_root_id`；artifact/watch event 相对 output root；input-access event 的路径相对其 root ID。所有目录遍历由 held directory descriptor 逐组件 no-follow 打开并核对身份，禁止 symlink 组件。

| Object | Exact fields / type constraints |
|---|---|
| `identity` | `scope_id`、`case_id` 精确匹配冻结 source receipt 中的 ASCII 值；`scope_receipt_sha256`、`definition_control_pack_sha256`、`initial_state_manifest_sha256` 为恰 64 小写 hex；`attempt_id` canonical lowercase UUIDv4；`attempt_nonce` 为 32-byte lowercase hex。 |
| `dependency_pins` | exact object `{source_pack,build_closure,output_inventory,input_trace_profile,supervisor_profile,runtime_environment,trust_registry}`；每个成员 exact `{schema_id,canonical_payload_sha256}`。schema ID 依序固定为 `core.cfd.f8.r008.frozen_source_pack.v1`、`core.cfd.f8.r008.build_closure.v1`、`core.cfd.f8.r008.output_inventory.v1`、`core.cfd.f8.r008.input_trace_profile.v1`、`core.cfd.f8.r008.supervisor_profile.v1`、`core.cfd.f8.r008.runtime_environment.v1`、`core.cfd.f8.r008.supervisor_trust_registry.v1`；hash 均为恰 64 小写 hex。各 pair 必须等于独立 trust root 预登记值，不得由 receipt 注册。现缺 build/inventory/trace/supervisor/runtime-environment/trust-registry 工件，故验证不可用。 |
| `solver` | `backend="cpu"`；`piece_count` exact int `1`；`source_root_id` 为 registry 中 immutable root ID；`source_hashes` array 1..16384 个 exact `{path,sha256}`，path 相对 source root、1..1024 ASCII bytes、严格 bytewise 排序且唯一；`source_closure_sha256`、`executable_sha256`、`build_config_sha256`、`runtime_environment_sha256` 均为恰 64 小写 hex。source list 必须与被 pin build-closure receipt 的完整 compiler/dependency closure 相等。 |
| `invocation` | `argv_count` exact int 1..256，包含 argv[0]；`argv_nul_joined_base64` 是 canonical padded RFC 4648 base64，payload 精确为 OS bytes `argv[0] || NUL || ... || argv[n−1] || NUL`，arg 不含 NUL，严格 decode/re-encode byte-identical、末尾恰一个 NUL，split 后恰 `argv_count` 项，decoded ≤2 MiB；`argv_sha256` 是 decoded payload 的 SHA-256。supervisor 从身份绑定 child 捕获 argv；除 argv[0] 外禁止 ASCII whitespace，使官方 `JCfgRunBase` 参数拆分对每个 OS arg 保持单 token。options 必须按 SHA-pinned v5.4 `JCfgRunBase`/`JSphCfgRun::LoadOpts` profile 重算，未知项拒绝；禁止所有 `OPT` option，`opt_sources` exact empty array `[]`。`cwd_relative/cwd_dev/cwd_ino/cwd_mode` 标识 namespace 下 no-follow 打开的真实 cwd，dev/ino exact int 0..2^64−1，mode exact int 0..2^32−1 且 `stat.S_ISDIR`。`initial_state_manifest_sha256` 等于 identity 中的 hash。`t_end_ieee754_hex`、`effective_time_max_ieee754_hex` 是非 null canonical lowercase `float.hex()` 且 binary64 bits 相等。Verifier 扫描 argv 中全部 TMAX option，依源代码顺序以 C locale `atof` 重算；只接受 canonical finite nonnegative decimal token。最后一次赋值若 `>0`，`effective_tmax_override_ieee754_hex` 必须非 null 且 bitwise 等于 T_end；若无 token 或最后值为 `0`，它必须为 null，且 Definition 自身的 TimeMax 必须等于 T_end。此规则对应源码仅在 `cfg->TimeMax>0` 时覆盖 Definition；`TMAX:0` 是出现但未生效。禁止 `PARTBEGIN`、restart/append、非零 `NSTEPS` 及 true `SVSTEPS`。`nst_steps` exact int `0`；`sv_all_steps,sdat_info,sdat_binx,data_out_bi4,restart,append` 为 exact JSON bool，固定 `false,true,true,true,false,false`；`csv_numeric_locale="C"`、`runparts_csv_delimiter=";"`。这些事实必须从 raw argv、冻结 Definition 与 pinned option profile 重算，不得以字段自述代替。 |
| `process` | `supervisor_id` printable ASCII 1..128；`worker_id` canonical lowercase UUIDv4；`pid` exact int 1..2^31−1，`proc_start_ticks` exact int 1..2^63−1；start/exit monotonic ns exact int 1..2^63−1 且 exit > start；raw POSIX `wait_status=0`、`exit_code=0`、`terminating_signal=null`、`attempt_count=1`、`writer_count=1` 均为精确类型/值。`runtime_environment_sha256` 等于 solver 字段且等于受 pin runtime-environment payload SHA；supervisor 证明 exec 环境 `LC_ALL=C` 且 numeric locale 为 C；完整 source/build/runtime closure 必须排除其后 locale mutation。所有进程事实由受信 supervisor 捕获且唯一绑定 attempt。 |
| `namespace_root` | exact `{root_id,dev,ino,mode}`；root ID 由 trust registry 绑定已打开目录，receipt 不得指定主机路径；dev/ino exact int 0..2^64−1；mode exact int 0..2^32−1 且 `stat.S_ISDIR(mode)`。 |
| `input_root` | exact `{relative_path,dev,ino,mode,snapshot_manifest_sha256}`；dev/ino unsigned-64，mode exact int 0..2^32−1 且 directory。整个 input tree 在 child 生命周期内 immutable/read-only；snapshot SHA 对应 pinned frozen source-pack canonical manifest，绑定全部 Definition/control/GenCase 初态输入。 |
| `output_root` | exact `{relative_path,dev,ino,mode,exclusive_writer}`；dev/ino unsigned-64、mode 为 directory，`exclusive_writer` exact bool true。目录由 trusted supervisor 为唯一 attempt 新建为空目录并锁定，不重用 namespace/旧输出；directory nlink 不要求为 1。 |
| `input_access` | exact `{coverage_start_monotonic_ns,coverage_stop_monotonic_ns,event_count,overflow,lost_events,unresolved_input_count,events}`；coverage 使用 process 同一 `CLOCK_MONOTONIC` 并严格覆盖 child start/exit；event_count exact int 0..8192 等于数组长度，overflow exact bool false、lost/unresolved exact int 0。events 连续 sequence 排序，每项 exact `{sequence,monotonic_ns,operation,role,root_id,path,dev,ino,size_bytes,sha256,accessed_bytes}`；operation 为成功的 `openat/read/pread64/mmap`，role 为 pinned input inventory 中 `definition/control/initial_state` 之一，path 相对该 root_id，所有数值 exact int 且限 unsigned-64。supervisor 从 syscall 与 held FD 采集，hash 完整文件 bytes；manifest 每个 required file 都须有对应成功 open 与正数 read/pread64/mmap bytes，身份/hash 精确相符。未知/外部路径、缺失事件、trace loss 或 manifest mismatch 均拒绝。由于 invocation 禁止 OPT，不允许 `opt` role/event。 |
| `termination_watch` | exact `{watcher_id,clock_id,watch_start_monotonic_ns,watch_stop_monotonic_ns,event_count,overflow,lost_events,events}`；watcher ID printable ASCII 1..128，clock literal `CLOCK_MONOTONIC`；times exact int 1..2^63−1 且 watch start < child start < child exit < watch stop；event_count exact int 0..4096 等于长度，overflow false、lost exact int 0。事件 exact `{monotonic_ns,sequence,kind,path_before,path_after,actor_pid}`，连续 sequence 1..event_count，monotonic ns exact int 且在 watch bounds 内，kind 为 `create/write/rename/unlink`，path relative output root，inapplicable path null，actor_pid exact int 1..2^31−1。trusted watcher 递归覆盖 output tree 且证明无丢失；不得触碰 TERMINATE path（rename 任一端也算）；覆盖不可证或空数组无完整 watcher 均拒绝。 |
| `artifacts` | array 1..2048；单项 ≤1 GiB、总字节 ≤16 GiB，按 output-root-relative path 严格 bytewise 排序且唯一；每项 exact `{path,role,size_bytes,sha256,dev,ino,nlink,mode,file_type}`。role 必须来自 pinned output inventory；size/dev/ino unsigned-64，sha lower hex，nlink exact int 1，mode exact int 0..2^32−1 且 `stat.S_ISREG`，file_type literal `regular`。required paths/counts 由冻结 output mode/inventory 重算；未知文件拒绝。退出后 no-follow reopen，用同一 bounded read bytes 作 hash+parse，fstat 前后 identity/size 必须不变。 |
| `attestation` | exact `{key_id,algorithm,payload_sha256,signature_base64}`；algorithm literal `Ed25519`，key_id printable ASCII 1..128，payload hash lower hex；签名 canonical padded RFC 4648 base64 且 strict decode/re-encode byte-identical，解码恰 64 bytes。公钥、有效期、scope/host 限制、revocation 来自 pinned trust registry。 |

Hard limits：receipt ≤64 MiB，depth ≤8，string 全部 printable ASCII，path 1..1024 bytes；artifact/item 总量上限如上。JSON float 禁止；binary64 用 round-trip canonical Python `float.hex()`；hash 恰 64 lowercase hex；int 是 JSON integer token 且 exact-type 验证拒绝 bool；所有资源上限在 allocation 前检查。Canonical JSON bytes 精确遵循 §3.1。

### 3.3 Exact signature message

Construct `payload_object` by removing only top-level `attestation`. Let `payload_bytes` be the exact canonical JSON encoding in §3.1, and `domain = ASCII("CORE-F8-R008-TERMINAL-COMPLETION-EVIDENCE-V3") || 0x00`. Require `attestation.payload_sha256 == SHA256(payload_bytes)`. Ed25519 verifies `signature_base64` over `domain || payload_bytes`; no other bytes, newline, pretty-print form, or transport wrapper are signed. The pinned trust registry and attested execution source are not currently available; v3 receipts cannot authenticate execution and remain diagnostic-only.

### 3.4 Pinned external dependencies 与 fail-closed verification order

七组 dependency pin 的 `schema_id + canonical_payload_sha256` 必须等于 task 外独立 trust root 预登记 pair；receipt 内的 key/path/caller JSON 不得建立信任。registry record 自身 canonical、签名且 hash 与 pinned trust anchor 一致。严格 verification order：

1. 对 receipt 原始 bytes 做严格 UTF-8、duplicate-key 拒绝、exact schema/type/bound 检查及 canonical-byte equality；
2. 从 task 外部 trust anchor 打开 trust registry，核验 registry 签名/schema/hash/有效期/revocation，并比对 receipt registry pin；
3. 以 registry 中 scope-limited Ed25519 key 验证 §3.3 receipt 签名及 attempt/host；
4. 验证 source/build/output/input-trace/supervisor/runtime-environment dependency 的 schema/hash/签名，确认 root ID 与 held descriptors/namespace 映射；
5. 用 hash-pinned v5.4 parser 重算 argv/Definition/options，核验 input trace、locale、process/watcher；
6. no-follow reopen outputs，解析与重算 RunPARTs/native PART/footer/末次 SaveData/output inventory；任一步缺证据均为 `missing/open`，不授予资格信用。

当前 trust anchor、registry、supervisor、input trace、build closure 与 output inventory 均不可用；v3 不产生可信 receipt、不接 gate，也不解除 R008 执行准入。

### 3.5 Deterministic RunPARTs CSV and time comparison

`RunPARTs.csv` uses the SHA-pinned v5.4 writer dialect: strict UTF-8 without BOM, LF only (no CR), no quotes, fixed semicolon delimiter, exact 26-column native header, contiguous data rows, one blank line, then the exact 26 one-cell footer lines in source order, final LF and no trailing bytes. Header/footer spellings and data-row width are pinned by the frozen output-inventory/parser contract; malformed, duplicate, reordered, omitted or extra rows fail closed. The writer constructs `JSaveCsv2(file,true,false)` and explicitly disables auto-separator rewriting for numeric data, so the RunPARTs delimiter is `;` irrespective of the general `CSVSEP` setting. `fun::RealStr(double)` resolves to `RealStr(v,16,true)` in this source revision.

The final BI4 `PART_####` `TimeStep` is decoded as little-endian IEEE-754 binary64 and compared to frozen `T_end` with no tolerance: `part_time >= t_end`. For each matching RunPARTs row, the raw `TimeStep [s]` cell bytes must equal the exact output of the SHA-pinned v5.4 `fun::RealStr(native_part_time,16,true)` under the locale attested by the supervisor profile; the contract requires locale `C` at exec and no later locale mutation; the semicolon dialect is fixed above. The numeric token is not accepted merely because a generic parser finds it “close”. An implementation may use the existing Python formatter only after exhaustive tests prove byte-for-byte equivalence on every reachable R008 time value; otherwise it must implement the source formatter semantics and test against official-source fixtures.

## 4. Recomputed terminal and last-save proof

The consumer parses raw `RunPARTs.csv`, solver log and final native PART bytes itself; receipt fields cannot override them. For the exact same successful run:

1. Frozen output schedule, `Part` sequence, initial `Part=0/time=0/Steps=0`, RunPARTs footer, and expected C-frame inventory all match; no duplicate, omitted, appended or partial row/frame.
2. Exact integer sum of all RunPARTs `Steps` increments equals terminal log `Steps of simulation: Nstep`; RunPARTs row count equals terminal `PART files` count.
3. Last main BI4 `PART_####` has `Cpart == final RunPARTs.Part`, `Step == Nstep`, and finite binary64 `TimeStep >= frozen T_end`; raw `PartInfo` and RunPARTs rows cross-match under §3.5.
4. Log contains one terminal `Simulation finished`, not `Simulation INTERRUPTED`; no minimum-fluid or nonzero `NSTEPS` warning, no `TERMINATE` update, process exit status is zero without signal/cancel, and supervisor confirms one attempt/writer and complete termination-watch coverage.
5. Every required artifact is reopened after process exit through a no-follow held descriptor, bounded-parsed, hashed and identity-checked. Any BI4 close/write issue that leaves missing or malformed bytes therefore fails this check even if the solver returned success.

Given fresh initial state, frozen `TimeMax=T_end`, positive validated `stepdt`, no dynamic horizon modification and no debug break, source loop condition implies the final applied step starts below `T_end` and crosses it. `RunPARTs.Steps` telescopes from the initial zero-step row to terminal `Nstep`; final `PartInfo.Step==Nstep` proves final `SaveData()` occurred on that last step. Source then executes `PartsOut->Clear()` after `SavePartData()` returns. A validated nonzero PartOut payload must also match that PART's RunPARTs counts/IDs/Motive; a zero row need not have a PartOut item.

If any proof input is absent, untrusted, ambiguous, not reopenable, or fails an equality, output `terminal_completion=missing/open`; do not infer from `Simulation finished`, exit code, final file name, or zero event count alone.

## 5. “Flush” durability boundary and gate status

这里的完成含义是**writer 调用路径完成 + 进程退出后读取到的文件当前可见且解析/hash 完整**。不含 `fsync`/目录 `fsync`、掉电、内核崩溃、设备缓存或远端存储持久性保证。若需求是抗掉电 durability，必须另建并审查 OS/filesystem durability protocol，不能引用本合同。

本合同不增加 gate，也不改变 native-integrity registry v1。即使终端证据完整且 exclusion 计数为零，`excluded_fluid_particles_zero` 仍只能是 `open/missing`；可信正排除在完整对账时才可为 `defined_fail`。`native_state_finite`、wall、overlap 等 gate 状态与 qualification credit 不变。

## 6. 只读复核问题

1. `PARTBEGIN:12:0:<dir>` 能否在 `PartIni/TimeStepIni` 为零时加载 restart？v3 对 fresh-run 的输入来源拒绝规则是否足够？
2. exact-field keys/types/bounds、canonical JSON bytes、Ed25519 domain/payload 及分离 trust-registry 的边界是否精确可实现？
3. RunPARTs 原生 16 位 formatter、CSV 分隔行为与 final BI4 binary64 时间比较合同是否准确且无隐含 tolerance？
4. `SaveData`/`PartsOut::Clear` 的逻辑完成与进程退出后可见文件、掉电 durability 的区分是否符合源码？
5. 是否仍存在 argv/parser/locale/normal-exit/restart/output-mode/attempt provenance false-pass？

只做只读设计复核；不编辑文件、不运行测试或工具、不读取生产 bundle/HDF5/frame，不运行 GenCase/native decoder/solver/worker/GPU/queue。
