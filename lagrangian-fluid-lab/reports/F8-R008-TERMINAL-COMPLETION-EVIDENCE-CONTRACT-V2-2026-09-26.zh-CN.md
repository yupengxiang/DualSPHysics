# F8 R008 terminal completion and artifact-visibility evidence contract v2

状态：只读设计修订，待独立复核。v2 additive supersede v1，保留 v1 与 review history。它不实现 verifier、不增加 gate、不修改 frozen scope/registry/分母/权限，不读生产数据，不执行 GenCase/native decoder/solver/worker/GPU/queue。v2 只证明“可信 attempt 在最后已应用 CPU timestep 完成 SaveData 调用路径，且进程退出后所需 writer artifacts 当前可重新打开并复验”；**不声称 fsync/断电持久化**，不认证当前不存在的 worker/key，也不授予资格信用。

## 1. v1 复核 findings 与关键修正

只读技术复核结论 `REVISE`（审阅者未 attestate 模型身份，不记模型签核）：

- **P1 fresh-run false pass：** `PartIni=0`、`TimeStepIni=0` 不足以证明 fresh run。官方 OPT 支持 `PARTBEGIN:12:0:<dir>`；内部 `PartIni=PartBeginFirst=0`、`TimeStepIni=0`，但粒子仍由旧 `PART_0012` 加载。v2 因此要求无 `PARTBEGIN`/restart source，并绑定冻结 initial-state bytes 与实际加载来源。
- **P2 receipt 语义不够 machine-exact：** v1 只列了字段分组，未冻结所有 exact keys/types、canonical receipt bytes、signature payload bytes 与 RunPARTs 时间文本算法。v2 固定 exact-field schema、类型/边界、canonical JSON 和 domain-separated Ed25519 payload；RunPARTs 时间文本须逐字等于固定官方 `RealStr(double,16,true)` 在冻结 CSV locale 下的结果，不能临时换用未证明等价的数值容差或格式器。
- **P3 “flush”措辞超出源码保证：** CSV writer 在写入时 `flush()` 并检查 stream error；BI4 `SaveFile()` 写后检查 stream 状态并关闭，但没有 `fsync`，也没有检查 close 后的错误。故 v2 只声称正常进程内写入路径完成且退出后重新打开的 artifact bytes 当前可见、可解析并可 hash；不声称抗断电/内核崩溃持久性。若后处理 reopen/parse/hash 失败，即使 solver exit 0 也不闭合。

## 2. 固定适用域与 fresh-run 证明

适用域仅为 frozen R008 的 CPU single-piece、一个 solver process、一个 attempt、一个独占 output writer；不接受 GPU、多-piece、restart、append、resume 或 output namespace 重用。必须绑定以下原始输入：frozen `Definition/control` pack、GenCase initial-state bytes/manifest、准确的 case directory identity、OPT 原始 bytes、argv 原始 bytes、solver/build/runtime identity。

fresh-run 不由 caller 的 `fresh=true` 或 `PartIni=0` 声明推导。消费端必须从原始 argv/OPT 重算：`PARTBEGIN` 不存在，`PartBegin=0`、`PartBeginFirst=0`、`PartBeginDir` 为空，restart/append 参数不存在；实际 `LoadParticles` 输入必须与冻结 GenCase initial-state manifest 精确同源且 SHA/inode 验证通过。任何 PARTBEGIN 字段被遮蔽、OPT parse 未覆盖的 token、目录重绑定或来源不匹配均 `missing/open`。

有效 `TimeMax` 必须经 v5.4 真实 option precedence 从 Definition 与 OPT 重算，IEEE-754 binary64 精确等于冻结 `T_end`。若存在 `TMAX` override，只允许其 parser 得到的 binary64 与 frozen `T_end` bitwise 相同；不接受不同值或用容差近似。`NSTEPS` 必须 absent/zero，`SVSTEPS` 必须 absent/false。其余 output cadence、`SDAT_Info`、`SDAT_Binx`、`DataOutBi4` 均须按 frozen contract 逐项重算。

## 3. receipt v2 exact wire schema

### 3.1 Raw bytes 与类型规则

整个 receipt 是 UTF-8 JSON，最多 64 MiB、最大嵌套深度 8；拒绝 BOM、无效 UTF-8、重复 key、未知/缺失字段、NaN/Infinity、JSON float 数值、非规范十进制整数及超限数组。解码后每个 JSON string 都须为可打印 ASCII；所有 binary64 时间以 canonical lowercase Python `float.hex()` string 表示，并须 round-trip `float.fromhex(s).hex()==s`；SHA-256 是恰 64 个小写 hex 字符。路径是 ASCII、相对于指定 root 的 POSIX 相对路径，1–1024 bytes；不允许绝对路径、`.`/`..`、空分量、NUL、反斜线或重复路径。整型字段必须是 JSON 整数 token（实现须用 `type(value) is int` 等价检查，拒绝 bool），且逐字段执行下表边界。JSON bytes 必须精确等于：

```text
json.dumps(object, ensure_ascii=False, sort_keys=True,
           separators=(",", ":"), allow_nan=False).encode("utf-8")
```

不带 BOM、前缀/尾随空白或 final newline。任何字段编码、key 排序或序列化差异均拒绝。

### 3.2 Top-level exact fields 与 nested fields

根对象恰含 `schema, identity, solver, invocation, process, namespace_root, input_root, output_root, termination_watch, artifacts, attestation`；`schema` 固定为 `core.cfd.f8.r008_terminal_completion_evidence.v2`。禁止嵌入 caller-authored derived status/pass/complete/flush 字段，派生结果只可由 verifier 对签名绑定的 artifacts 重算。`namespace_root.root_id` 必须在 supervisor trust registry 中预注册，receipt 不能自行指定其主机路径或身份；`namespace_root/input_root/output_root/cwd` 的 `relative_path` 均相对该已打开的 namespace 根目录，OPT item 的路径相对其 `root_id` 指定的 input 或已注册 immutable root，artifact/watch event 路径相对 output root。所有目录遍历按 held directory descriptor 逐组件 no-follow 打开，并核对身份，禁止符号链接组件。

| Object | Exact fields / type constraints |
|---|---|
| `identity` | `scope_id` (exact frozen ID string), `case_id` (one of 15 frozen IDs), `scope_receipt_sha256`, `definition_control_pack_sha256`, `attempt_id` (canonical lowercase UUIDv4), `attempt_nonce` (32-byte lowercase hex), `initial_state_manifest_sha256` (lowercase SHA-256)。 |
| `solver` | `backend` literal `cpu`, `piece_count` integer literal `1`, `source_hashes` array of exact `{path,sha256}` items strictly bytewise path-sorted/no duplicates and ≤16384 entries, `source_closure_sha256`, `executable_sha256`, `build_config_sha256`, `runtime_environment_sha256` (all lowercase SHA-256)。The list must equal the compiler-dependency source/header closure in the separately pinned build receipt; missing build-closure receipt makes verification unavailable, not caller-selectable. |
| `invocation` | `argv_count` exact int 1..256; decoded argv payload ≤2 MiB; after strict decode, NUL-splitting yields exactly `argv_count` argument byte strings plus the single terminal empty segment, and rejoining reproduces the bytes; `argv_nul_joined_base64` canonical padded RFC 4648 standard base64 of `argv[0] || NUL || ... || argv[n-1] || NUL` using exact OS argument bytes (OS arguments cannot contain NUL); strict decode/re-encode must reproduce the field byte-for-byte; `argv_sha256` is SHA of decoded bytes. The supervisor captures argv from the identified child, not caller text. `opt_sources` array 0..64 of exact `{root_id,path,bytes_base64,sha256,size_bytes,dev,ino,nlink,mode}` entries in resolved load order; base64 uses the same strict canonical rule; each is a no-follow regular file with `nlink=1`, `size_bytes` equals decoded length and ≤64 KiB, aggregate decoded bytes ≤512 KiB, and `dev/ino` are exact ints 0..2^64−1, `nlink` exact int 1, `mode` exact int 0..2^32−1 with `stat.S_ISREG(mode)`, and all match the opened file; paths resolve beneath the named immutable root. `cwd_relative` plus `cwd_dev/cwd_ino/cwd_mode` identify the opened working directory beneath namespace root; dev/ino are exact ints 0..2^64−1 and mode is exact int 0..2^32−1 with `stat.S_ISDIR(mode)`. `initial_state_manifest_sha256` equals the identity object's value. `initial_state_manifest_sha256`; non-null canonical `t_end_ieee754_hex` and `effective_time_max_ieee754_hex` must be bitwise equal; `tmax_override_ieee754_hex` is null iff no override was parsed, otherwise canonical and bitwise equal to `t_end`. `nst_steps` exact int `0`; `sv_all_steps`, `sdat_info`, `sdat_binx`, `data_out_bi4`, `restart`, and `append` exact JSON booleans respectively `false,true,true,true,false,false`; `csv_numeric_locale="C"`, `runparts_csv_delimiter=";"`. `argv`/all recursively loaded OPT bytes and parsed effective options must agree; reject unrepresented/unknown options or sources. Every required field is present with its stated exact type; the verifier derives and rejects any `PARTBEGIN` token; there are no caller-supplied `PartBegin` fields. |
| `process` | `supervisor_id` printable ASCII length 1..128, `worker_id` canonical lowercase UUIDv4, `pid` 1..2^31−1, `proc_start_ticks` 1..2^63−1, `start_monotonic_ns`/`exit_monotonic_ns` 1..2^63−1 with exit > start and from the declared monotonic clock, `wait_status` raw POSIX wait status integer 0, `exit_code` integer 0, `terminating_signal` null, `attempt_count` integer 1, `writer_count` integer 1。Supervisor trust state must independently establish these refer to the same child and unique attempt. |
| `namespace_root` | exact fields `root_id,dev,ino,mode`; printable ASCII root ID resolves through the separately pinned supervisor registry to an already opened directory; `dev/ino` unsigned 64-bit; `mode` is exact int 0..2^32−1 and `stat.S_ISDIR(mode)` must hold. |
| `input_root` | exact fields `relative_path,dev,ino,mode,snapshot_manifest_sha256`; unsigned-64 identities and exact int mode 0..2^32−1 with `stat.S_ISDIR(mode)`. Its tree is an immutable, read-only snapshot for the full child lifetime. The manifest SHA is over canonical manifest bytes in the authenticated frozen source receipt and binds every Definition/control/initial-state/OPT input actually loaded. All loaded paths resolve beneath this root or a separately registered immutable root; unresolved external paths reject. |
| `output_root` | exact fields `relative_path,dev,ino,mode,exclusive_writer`; `dev/ino` unsigned 64-bit, mode exact int 0..2^32−1 with `stat.S_ISDIR(mode)`, `exclusive_writer` exact bool `true`. It is newly created empty for this attempt under the registered namespace; no pre-existing namespace or output files may be reused. Directory `st_nlink` is not constrained to 1. |
| `termination_watch` | exact object `{watcher_id,clock_id,watch_start_monotonic_ns,watch_stop_monotonic_ns,event_count,overflow,lost_events,events}`; `watcher_id` printable ASCII length 1..128, `clock_id="CLOCK_MONOTONIC"`; times exact int 1..2^63−1 satisfy watch-start < child-start < child-exit < watch-stop on that clock; `event_count` exact int 0..4096 equals array length, `overflow` exact bool `false`, `lost_events` exact int `0`. Events are exact items `{monotonic_ns,sequence,kind,path_before,path_after,actor_pid}`, sequence exact int contiguous 1..event_count, monotonic time exact int within watch bounds, `kind` one of `create/write/rename/unlink`, actor PID exact int 1..2^31−1; applicable paths are relative to output root and inapplicable paths null. Trusted watcher recursively covers output tree with proven zero event loss; no event may touch solver `TERMINATE` path (including either side of rename). If recursive loss-free coverage is unavailable, reject; empty array alone is not proof. |
| `artifacts` | array 1..2048, each ≤1 GiB and aggregate ≤16 GiB, sorted strictly by unique path relative to output root; each exact item `{path,role,size_bytes,sha256,dev,ino,nlink,mode,file_type}`. `role` is an enum fixed by the source-hashed output-inventory contract (including `solver_log`, `worker_stdout`, `worker_stderr`, `runparts_csv`, `main_bi4_part`, `part_info`, `part_head`, `partout_block`, `part_extra`, `part_motion_ref`, `part_float_info`, `solver_res`); `size_bytes/dev/ino` are unsigned 64-bit, `nlink=1`, `mode` identifies a regular file, `file_type="regular"`; no symlink, directory, device or FIFO. Required paths/counts are recomputed from the frozen output-mode and writer inventory; unknown output paths fail closed. Reopen each through a no-follow descriptor, fstat before/after the one bounded read, hash and parse those same bytes, then compare device/inode/mode/link-count/size. |
| `attestation` | exact fields `key_id,algorithm,payload_sha256,signature_base64`; algorithm literal `Ed25519`, key ID printable ASCII length 1..128, payload SHA-256 lowercase hex, signature canonical padded RFC 4648 standard base64, strict decode/re-encode byte-identical and exactly 64 decoded bytes. The key must resolve through a separately pinned trust registry with validity, scope/host restrictions and revocation state. |

The global 1 GiB/artifact and 16 GiB/receipt artifact-byte limits are hard schema caps; frozen inventory may impose smaller per-role caps and exact cardinalities. Receipt/event/artifact limits must be checked before allocation. If the inventory does not provide finite per-role caps, verification is unavailable.

### 3.3 Exact signature message

Construct `payload_object` by removing only top-level `attestation`. Let `payload_bytes` be the exact canonical JSON encoding in §3.1, and `domain = ASCII("CORE-F8-R008-TERMINAL-COMPLETION-EVIDENCE-V2") || 0x00`. Require `attestation.payload_sha256 == SHA256(payload_bytes)`. Ed25519 verifies `signature_base64` over `domain || payload_bytes`; no other bytes, newline, pretty-print form, or transport wrapper are signed. The trust registry is not currently available, so v2 receipts cannot presently authenticate execution and remain diagnostic-only.

### 3.4 Deterministic RunPARTs CSV and time comparison

`RunPARTs.csv` uses the SHA-pinned v5.4 writer dialect: strict UTF-8 without BOM, LF only (no CR), no quotes, fixed semicolon delimiter, exact 26-column native header, contiguous data rows, one blank line, then the exact 26 one-cell footer lines in source order, final LF and no trailing bytes. Header/footer spellings and data-row width are pinned by the frozen output-inventory/parser contract; malformed, duplicate, reordered, omitted or extra rows fail closed. The writer constructs `JSaveCsv2(file,true,false)` and explicitly disables auto-separator rewriting for numeric data, so the RunPARTs delimiter is `;` irrespective of the general `CSVSEP` setting. `fun::RealStr(double)` resolves to `RealStr(v,16,true)` in this source revision.

The final BI4 `PART_####` `TimeStep` is decoded as little-endian IEEE-754 binary64 and compared to frozen `T_end` with no tolerance: `part_time >= t_end`. For each matching RunPARTs row, the raw `TimeStep [s]` cell bytes must equal the exact output of the SHA-pinned v5.4 `fun::RealStr(native_part_time,16,true)` under process `LC_NUMERIC=C`; the semicolon dialect is fixed above. The numeric token is not accepted merely because a generic parser finds it “close”. An implementation may use the existing Python formatter only after exhaustive tests prove byte-for-byte equivalence on every reachable R008 time value; otherwise it must implement the source formatter semantics and test against official-source fixtures.

## 4. Recomputed terminal and last-save proof

The consumer parses raw `RunPARTs.csv`, solver log and final native PART bytes itself; receipt fields cannot override them. For the exact same successful run:

1. Frozen output schedule, `Part` sequence, initial `Part=0/time=0/Steps=0`, RunPARTs footer, and expected C-frame inventory all match; no duplicate, omitted, appended or partial row/frame.
2. Exact integer sum of all RunPARTs `Steps` increments equals terminal log `Steps of simulation: Nstep`; RunPARTs row count equals terminal `PART files` count.
3. Last main BI4 `PART_####` has `Cpart == final RunPARTs.Part`, `Step == Nstep`, and finite binary64 `TimeStep >= frozen T_end`; raw `PartInfo` and RunPARTs rows cross-match under §3.4.
4. Log contains one terminal `Simulation finished`, not `Simulation INTERRUPTED`; no minimum-fluid or nonzero `NSTEPS` warning, no `TERMINATE` update, process exit status is zero without signal/cancel, and supervisor confirms one attempt/writer and complete termination-watch coverage.
5. Every required artifact is reopened after process exit through a no-follow held descriptor, bounded-parsed, hashed and identity-checked. Any BI4 close/write issue that leaves missing or malformed bytes therefore fails this check even if the solver returned success.

Given fresh initial state, frozen `TimeMax=T_end`, positive validated `stepdt`, no dynamic horizon modification and no debug break, source loop condition implies the final applied step starts below `T_end` and crosses it. `RunPARTs.Steps` telescopes from the initial zero-step row to terminal `Nstep`; final `PartInfo.Step==Nstep` proves final `SaveData()` occurred on that last step. Source then executes `PartsOut->Clear()` after `SavePartData()` returns. A validated nonzero PartOut payload must also match that PART's RunPARTs counts/IDs/Motive; a zero row need not have a PartOut item.

If any proof input is absent, untrusted, ambiguous, not reopenable, or fails an equality, output `terminal_completion=missing/open`; do not infer from `Simulation finished`, exit code, final file name, or zero event count alone.

## 5. “Flush” durability boundary and gate status

这里的完成含义是**writer 调用路径完成 + 进程退出后读取到的文件当前可见且解析/hash 完整**。不含 `fsync`/目录 `fsync`、掉电、内核崩溃、设备缓存或远端存储持久性保证。若需求是抗掉电 durability，必须另建并审查 OS/filesystem durability protocol，不能引用本合同。

本合同不增加 gate，也不改变 native-integrity registry v1。即使终端证据完整且 exclusion 计数为零，`excluded_fluid_particles_zero` 仍只能是 `open/missing`；可信正排除在完整对账时才可为 `defined_fail`。`native_state_finite`、wall、overlap 等 gate 状态与 qualification credit 不变。

## 6. 只读复核问题

1. `PARTBEGIN:12:0:<dir>` 能否在 `PartIni/TimeStepIni` 为零时加载 restart？v2 对 fresh-run 的输入来源拒绝规则是否足够？
2. exact-field keys/types/bounds、canonical JSON bytes、Ed25519 domain/payload 及分离 trust-registry 的边界是否精确可实现？
3. RunPARTs 原生 16 位 formatter、CSV 分隔行为与 final BI4 binary64 时间比较合同是否准确且无隐含 tolerance？
4. `SaveData`/`PartsOut::Clear` 的逻辑完成与进程退出后可见文件、掉电 durability 的区分是否符合源码？
5. 是否仍存在 normal-exit/restart/output-mode/attempt provenance false-pass？

只做只读设计复核；不编辑文件、不运行测试或工具、不读取生产 bundle/HDF5/frame，不运行 GenCase/native decoder/solver/worker/GPU/queue。
