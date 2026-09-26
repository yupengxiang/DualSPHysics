# F8 R008 Terminal Completion Evidence Contract v17

**状态：**proposal-only / diagnostic-only；不是 trusted launcher、fanotify responder、syscall policy 或 kernel observer 的实现，也不证明 runtime readiness。V16 经 Terra High 配置只读复核为 `REVISE`、无 P0，模型身份未获 attestation。V17 仅修订静态合同中的兼容性、启动顺序、因果引用和当前 wire schema；F8 仍为 `runtime-readiness=false`。

## 0. 生效范围与历史 schema 归属

V17 是当前 proposal 的唯一解释；V16 及更早文件保持不可变历史。除本版明确覆盖的范围外，V16 §2 的 x86-64 syscall suppression 与 §6 的 backing-OFD/final-fput 目标模型仍只是待实现合同，不代表已通过内核源码证明或可执行。

| 字段/规则族 | 当前归属 |
|---|---|
| V3–V7 terminal timestep、fresh-run、签名/trust、BI4/RunPARTs 科学语义、output inventory、read-only seal、zero-credit 边界 | 继续有效；其运行机制以 V16 §2–7 及本版明确修订为准 |
| V8 permission/name event bytes 与字段 | 仅允许旧 artifact 的 `V8` decoder 历史解码；不得作为当前 receipt 或当前 F8 证据 |
| V9–V16 token / syscall / fanotify / launcher / copy-out / close 运行机制 | 历史提案；本版 §1–5 明确覆盖处优先，否则仍是 proposal-only 条款 |
| V13 `initial_maps_snapshot` disjoint raw-row 数据模型、V14 有界 `/proc/maps` 原始字节字段 | 仅在各自 schema/version 下继续适用于 maps；不延伸至 fanotify 事件 |
| 当前 fanotify raw event 和 permission action | 只接受本版 §3.1 定义的 `f8-fanotify-raw-v1` / `f8-fanotify-action-v1` |
| 当前 kernel-observer raw row | 只接受本版 §4 的 `f8-final-fput-observer-row-v1`；其 schema 存在不表示 observer 已实现 |

旧 receipt 缺少本版必填字段时必须标记 `historical_only`，不得通过默认值、字段别名或重解析补成当前 receipt。每条当前 row 必须带唯一 `schema`；未知 schema、字段重复、缺字段、额外未登记字段均拒绝。

## 1. Token 因果引用修订

覆盖 V16 §1 的 `causal_parent_refs` 枚举：允许的 `ref_kind` 精确为 `target_syscall | supervisor_operation | terminal_exit | census_epoch | cgroup_empty`。`cgroup_empty` 是有独立 ID 的不可变 census receipt，不是 `census_epoch` 的隐式别名；receipt 至少绑定 `{attempt_id,cgroup_id,cgroup_inode,epoch_id,freeze_readback_bytes,procs_before_digest,procs_after_digest,populated_readback_bytes,task_inventory_digest,observed_empty=true,record_seq}`。

`output_seal` 必须直接引用唯一、已验证且先于 seal 的 `cgroup_empty` receipt，以及该 attempt 每个 output object 的全部 `terminal_fd_close` operation refs。`terminal_fd_close` 仍须引用已验证 terminal exit 与该 object 的所有最后写 token。丢失、重复、跨 attempt、次序错误或 epoch 不匹配一律保持 open/missing。

## 2. Launcher / tracer / pre-exec placeholder 的冻结状态机

覆盖 V16 §§3–4 中要求 `posix_spawn_file_actions_adddup2` 或 uncoordinated child-side `dup2` 的路径。V17 profile **不使用 `posix_spawn` file actions**。POSIX spawn file actions 是 spawn 操作的一部分并在新进程的 exec 前处理；该接口自身不给本合同所需的 tracer-stop / cgroup / placeholder 交接 receipt。[POSIX `posix_spawn`](https://pubs.opengroup.org/onlinepubs/9799919799/functions/posix_spawn.html)

受支持的 proposal 状态机如下；所有 bytes、hash、返回值、errno、PID/start-time generation 和单调序号需写入 hash-chained journal。child 的初始创建/exec trampoline 路径本身是 TCB；必须以源码、机器码和 syscall 清单 pin，且不能执行目标 image：

1. **PINNED**：可信父 supervisor 固定 launcher/supervisor binary 与 child fork-return stub 的 exact PC range/hash、静态 launcher-trampoline ELF bytes/hash/build ID/held-FD identity、目标 executable held-FD identity/hash、argv/env bytes、继承 FD allowlist、cgroup identity、namespace identity 与目标 profile。单一授权 pipe 的 child read-FD 与 parent write-FD、pipe inode、attempt binding 和固定 token bytes `0x47` (`G`) 均固定；parent 在 fork 后关闭 read-end，child 的 write-end 副本 FD_CLOEXEC=1 且 read-end 保持可读。child fork-return stub 唯一未追踪 syscall 是 `PTRACE_TRACEME`，随后立即 `int3`；初始 stop 后第一条 post-stop syscall 必须显式关闭 child write-end，成功后 parent 才是唯一 surviving writer，随后才在 trace 下 `execveat` 进入 pinned static trampoline。supervisor 在创建 child 前证明 SIGTRAP 为默认 disposition且未 blocked；否则不启动。该 trampoline exec 只运行 TCB，不能执行 target；read-end 保留至授权后由受 ptrace 的 trampoline 关闭。每 attempt 新建 pipe，token 的 attempt binding 由 pipe inode/launch receipt 绑定，不依赖跨 attempt secret。不得有动态 loader 或未 pin 的 child-side constructor。
2. **INITIAL_TRACE_STOP**：child fork-return stub 的唯一 bootstrap syscall 是 native x86-64 `ptrace(PTRACE_TRACEME)`；成功返回后立即执行单条 `int3`，两者之间不得有其他 syscall、thread、fork 或外部输入解析。父 supervisor 通过 `waitpid(__WALL)` 收到 `SIGTRAP` stop，核验 `PTRACE_GETSIGINFO.si_signo=SIGTRAP`、`si_code=TRAP_BRKPT`、`PTRACE_GETREGSET(NT_PRSTATUS).rip == pinned_int3_pc+1` 及该映射中 trap byte 为 `0xcc`；PID/start ticks 与 pinned launcher/supervisor code mapping/hash 也须相符。随后以一次成功的 `PTRACE_SETOPTIONS` 设置精确冻结的 `PTRACE_O_TRACESYSGOOD|PTRACE_O_TRACECLONE|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACEEXEC|PTRACE_O_TRACEEXIT|PTRACE_O_EXITKILL`，journal 保存 mask、request/return/errno；任一选项不受支持即拒绝。Linux ptrace ABI 没有通用 `PTRACE_GETOPTIONS` readback request，因此本合同不声称有该 readback；精确 request/成功返回必须由 pinned-source 与 event conformance 证明，后续真实 `PTRACE_EVENT_EXEC` 亦须见证 `TRACEEXEC` 生效。`PTRACE_O_TRACEEXEC` 是必需项，缺省时不能依赖 `PTRACE_EVENT_EXEC`。[ptrace(2)](https://man7.org/linux/man-pages/man2/ptrace.2.html) 该 pinned bootstrap 只含在 TCB 内，不是 target 指令。pre-trace 的 `PTRACE_TRACEME` 是唯一明示例外，不声称不存在 pre-trace syscall。
3. **CGROUP_BOUND**：child 保持初始 ptrace-stop，父 supervisor 将其加入专属 cgroup-v2 leaf，读回并绑定 cgroup inode、`cgroup.procs`、`cgroup.events`、mount/proc view 与 lineage。不可变 `root_launch_record` 必须证明 child 与 launcher 不共享 `mm_struct`/`files_struct`；所有可见 peer 都进入同一冻结 census 闭包。所有 prerequisite 完成前不得发送授权 token。
4. **CHILD_WRITER_CLOSED**：父 tracer 以 `PTRACE_SYSCALL` 且 signal 参数为 0 抑制 bootstrap `SIGTRAP` 恢复 child；child 下一条 syscall 必须是 `close(child_write_fd)`。tracer 核验精确 FD generation，只有 close exit `ret=0` 才记 `child_writer_close_ref` 并进入下一态；close 出错时 pinned stub 立即执行 fail-closed `_exit`，禁止 trampoline exec/pool/target。若 tracer 在此 close 前死亡，内核可能 detach/restart tracee；此非 qualifying 路径仍只允许 pinned stub 尝试该 close，close 失败即退出；父唯一 writer 因死亡关闭，故后续 gate 只能 EOF。完整 attempt 必须有 traced close receipt，任何 tracer death/未配对 close 都使 attempt incomplete。
5. **TRAMPOLINE_EXEC_EVENT_STOP**：child writer 已成功关闭且 `PTRACE_O_TRACEEXEC`、cgroup/lineage/census 均已闭合后，下一条 syscall 必须是以 pinned held FD/固定 argv-env 执行 trampoline `execveat`；tracer 校验 entry args，并且只接受其 `PTRACE_EVENT_EXEC` stop。execveat 若失败，stub 立即 `_exit`，不得转入 pool/target；成功时在恢复前校验新 image bytes/hash/build ID、entry mapping、FD inheritance、pipe endpoint closure 与 parent/cgroup lineage。此 stop 前后只允许受 pin 的 trampoline TCB，不能是 target image。
6. **AUTHORIZATION_GATE**：trampoline 启动后第一条 syscall 必须是对精确 read-FD、1-byte buffer/length 的单次 gate `read()`；tracer 校验 syscall-entry 后才恢复该 read。父 supervisor 只在 `PTRACE_O_EXITKILL` 已成功设置且 child writer close/cgroup/lineage/census/FD inventory 均闭合后，向 sole writer 写恰好一个 `0x47` byte；read exit-stop 必须返回 `1` 且 bytes 等于 `0x47`，随后 trampoline 关闭 read-FD，记录 close 成功。token 缺失、EOF、短读、EINTR、错误 token、父 setup failure 或任何 tracer error 均不可创建 pool/执行 target；父在 setup failure 时关闭 writer 并保持/恢复 child 仅用于观察 gate EOF 后的 fail-closed exit。

    tracer-death race 的规范行为：`PTRACE_O_EXITKILL` 生效后 tracer death 必须杀死 tracee；若 tracer 在设置 `EXITKILL` 前退出，kernel detach 后 child 最多执行已 pin 的 writer-close、trampoline exec 与 gate read；close 成功会移除 child writer，父唯一 writer 随进程退出而关闭，gate read 得 EOF，trampoline 必须立即 fail-closed 退出，绝不继续 pool/target exec。writer-close 或 trampoline exec 任一失败均立即退出。初始 trap 前若 tracer不存在，默认 `SIGTRAP` action 必须终止 child。pipe endpoint/FD inheritance、signal mask/default dispositions 与以上 failure path 均需 pinned-kernel conformance 证据。
7. **POOL_BUILT_UNDER_TRACE**：gate token 验证且 read-FD 成功关闭之后，trampoline 的每个 syscall 都先收到 ptrace entry stop，再由固定 policy 决策。trampoline 用冻结的 source FD 对每个精确 slot 执行受审计的 `dup3`/必要 `fcntl`，核验 `FD_CLOEXEC=0`、`fstat` identity、`RLIMIT_NOFILE`、slot 冲突及完整 FD inventory；pool receipt 和 syscall entry/exit sequence 必须一一对应。不得使用未记录的 child-side file action。
8. **TARGET_EXEC_EVENT_STOP**：trampoline 以 held target executable FD 执行唯一冻结的 `execveat(...,AT_EMPTY_PATH)`。supervisor 必须收见相符的 `PTRACE_EVENT_EXEC`，在恢复 tracee 前复核 executable identity/hash、argv/env、FD pool、cgroup、namespace、mm/files generation、ptrace options 与 seccomp state。`PTRACE_EVENT_EXEC` 发生在 `execve` 返回前；确切 kernel profile 仍须 source-pin/conformance 证明 target 的任何指令都未在验证前执行。[ptrace(2)](https://man7.org/linux/man-pages/man2/ptrace.2.html)
9. **TARGET_RELEASED**：仅全部前项 receipt 完整、相互一致且 profile gate 通过后，tracer 才可继续 tracee；这时才允许执行目标 image 的首条指令。目标之后的所有 syscall 仍须符合 V16 §2 和完整逐号 deny/broker policy；pool 或 ptrace 任一不变量破坏即 fail closed。

此状态机只定义需实现的顺序，不证明某个 launcher 已满足它。trampoline 源码/机器码、receipt schema、exact kernel ptrace conformance、namespace/cgroup setup 和运行时测试均未提供前，runtime readiness 不变。

## 3. Fanotify scope：封闭目录 inode marks，不使用 mount marks

覆盖并取代 V16 §5 的 mount-scope 规则。V17 不接受 `FAN_MARK_MOUNT` 与需要 file-handle/FID 识别的目录项事件混用：对 `FAN_CREATE/DELETE/MOVE/RENAME/ATTRIB` 等相应 mask，mount mark 会使 `fanotify_mark()` 返回 `EINVAL`。[fanotify_mark(2)](https://man7.org/linux/man-pages/man2/fanotify_mark.2.html)

当前 proposal 的输出范围改为单一 attempt-private directory root `R`，所在文件系统必须在目标 pinned kernel 上支持所需 FID/file-handle 编码，报告可唯一关联的非零 FSID；不再假定 tmpfs 一定合格。fanotify FID API 对不支持 file handles 的 filesystem 会返回 `EOPNOTSUPP`；在 kernel 6.5+，`name_to_handle_at(...,AT_HANDLE_FID)` 可用于实现前的 filesystem 支持测试。任何 FSID/handle 重用不能被可靠区分、跨 filesystem、符号链接、bind/remount alias、root 外路径或不支持的 mount topology 均拒绝 profile；本轮没有执行这些测试。[fanotify_mark(2)](https://man7.org/linux/man-pages/man2/fanotify_mark.2.html)

在 target release 前，trusted supervisor 建立并冻结目录集合 `D0`：它包含 `R` 下所有允许的目录；所有目录预先存在、由 held directory FDs 逐一锚定、位于同一已验证 filesystem，且记录 parent/object identity 与拓扑 digest。两个 group 对 `D0` 中**每个目录 inode** 分别安装 mark；raw flags 精确为 `FAN_MARK_ADD|FAN_MARK_ONLYDIR`（无 `FAN_MARK_MOUNT` / `FAN_MARK_FILESYSTEM`，因此 scope 为 inode），mask 含各自事件位以及 `FAN_EVENT_ON_CHILD`，不含 `FAN_ONDIR`。逐 mark syscall bytes/result、目录 FD identity、`/proc/self/fdinfo` 完整 mark inventory 及总数上限均写 receipt。

`FAN_EVENT_ON_CHILD` 只覆盖已标记目录的直接 children，不会递归覆盖未标记的孙级目录。因此完整闭包依赖 `D0` 中每级目录均已预标记，并由 syscall policy 禁止运行中增加、删除、rename/move 任意目录或创建 mount/alias。regular leaf 的 create/write/close 只允许走 V16 的 broker/supervisor path；若目标 workload 必须在运行中创建目录、执行未支持的 namespace mutation、或涉及 root 外 object，本 proposal 不适用，不得缩窄观测范围继续执行。[fanotify_mark(2)](https://man7.org/linux/man-pages/man2/fanotify_mark.2.html)

| init / mask / mark | permission group | name/notification group |
|---|---|---|
| init flags | `FAN_CLASS_CONTENT|FAN_REPORT_PIDFD|FAN_CLOEXEC|FAN_NONBLOCK`，无 FID/TID report | `FAN_CLASS_NOTIF|FAN_REPORT_PIDFD|FAN_REPORT_DFID_NAME_TARGET|FAN_CLOEXEC|FAN_NONBLOCK`，无 permission/TID bits |
| `fanotify_init()` event_f_flags 第二实参 | 精确 `O_RDONLY|O_CLOEXEC|O_LARGEFILE` | 精确 `O_RDONLY|O_CLOEXEC|O_LARGEFILE`；虽然 FID mode 下 `metadata.fd=FAN_NOFD` 且不产生 object event-FD，init 参数仍记录相同固定值 |
| 每个 D0 directory mark mask | `(FAN_OPEN_PERM|FAN_ACCESS_PERM|FAN_OPEN_EXEC_PERM)|FAN_EVENT_ON_CHILD` | `(FAN_CREATE|FAN_MODIFY|FAN_CLOSE_WRITE|FAN_OPEN|FAN_ACCESS|FAN_CLOSE_NOWRITE)|FAN_EVENT_ON_CHILD` |
| hard prerequisite | `FAN_CLASS_CONTENT` permission profile 需要 `CAP_SYS_ADMIN`；同时要求 kernel 配置支持 permission events | FID/name profile 与每个 marked directory 的 file-handle support、FSID/object-generation join 必须通过 pinned-kernel conformance |

CAP_SYS_ADMIN、fanotify 配置、mark quota、queue bound、filesystem file-handle 支持任一不满足则无 attempt。此为 capability/profile 门槛，不授权也不构成本轮主机探测。man-pages 明确 `FAN_CLASS_CONTENT` 需要 `CAP_SYS_ADMIN`；非特权 group 不能建立 permission-event class。[fanotify_init(2)](https://man7.org/linux/man-pages/man2/fanotify_init.2.html)

### 3.1 当前 fanotify wire schema

`f8-fanotify-raw-v1` 是只读原始事件 row，精确字段为：

```text
{schema,attempt_id,group_id,group_kind,group_seq,read_seq,raw_record:{bytes_b64,byte_len,sha256},metadata:{event_len,vers,reserved,metadata_len,mask,fd,pid},info_records:[{type,len,bytes_b64}],mark_inventory_digest,actor_pidfd_ref,event_fd_ref}
```

`raw_record.bytes_b64` 是一次 `read()` 返回缓冲区中该事件完整 `event_len` 的原始 bytes；`info_records` 是从同一原始片段按 pinned UAPI parser 导出的冗余字段，verifier 必须逐字节重解析并比对，不得单独信任 parsed rows。列表次序必须与原始 byte offset 一致。`group_seq` 仅在单个 group 内连续；不表示两个 queue 间的全序。字段 nullability 精确按 group 分支：

- `group_kind=permission`：`metadata.fd >= 0` 且 `event_fd_ref` 非 null；恰有一个 PIDFD info row；FID/DFID/name rows 不允许。event FD 必须以独立 action row 完成 object `fstat/statx`、response 和 close lifecycle。`actor_pidfd_ref` 必须非 null。
- `group_kind=name`：`metadata.fd == FAN_NOFD` 且 `event_fd_ref == null`；恰有一个 PIDFD info row；要求 FID 的 event 必须按下列 mask-specific grammar 带 FID records。`actor_pidfd_ref` 必须非 null。FID group 中 `FAN_NOFD` 是规定值，不是失败；permission group 中负值/`FAN_NOFD` 才是失败。

每个 PIDFD info record 的 raw PIDFD number 都必须有唯一 `f8-fanotify-pidfd-action-v1` 生命周期 receipt：`{schema,attempt_id,group_id,group_seq,pidfd_info_index,pidfd_number,fdinfo_raw_bytes_b64,metadata_pid,task_generation_ref,held_pidfd_ref,close_ret,close_errno}`。它记录该 descriptor 从 read buffer 安装至 actor generation join、close 的全过程；`pidfd_number < 0`、PIDFD 的 fdinfo/PID/start-time generation 无法与冻结 census 中唯一 actor 对应、重复引用或 close 不成功均 incomplete。`actor_pidfd_ref` 必须精确引用此 row，不能只保存 PID 数字。

当前 marks 不含 `FAN_ONDIR`，scope 只包括预建目录的 regular-file children；target policy 除 `fresh-create/append-only` 外，拒绝任何 `mkdir/rmdir/rename/link/unlink/symlink/mount` 以及 metadata mutation。`FAN_DELETE_SELF`、`FAN_MOVE_SELF`、`FAN_DELETE`、`FAN_MOVE`、`FAN_RENAME`、`FAN_ATTRIB` 不属于本 profile 的 mark mask，也不作为 child coverage 证据；任何此类实际事件/请求均为 policy violation/incomplete。这样不依赖对 unmarked child inode 的 `FAN_DELETE_SELF`/`FAN_MOVE_SELF` 通知。按 V17 init flags 与普通 linked regular-file 前置条件，name group 对 mask 中每一种事件 `CREATE/MODIFY/CLOSE_WRITE/OPEN/ACCESS/CLOSE_NOWRITE` 的 record multiset 精确为一个 `PIDFD + FID + DFID_NAME`；重复、缺失、未列类型或多余 record 均 incomplete。记录原始次序和 bytes，但 verifier 按该固定 multiset 验证。该 grammar 对应 [fanotify_init(2)](https://man7.org/linux/man-pages/man2/fanotify_init.2.html) 的 FID/name/target-FID 规则，仍须对确切 pinned kernel 提供 parser vectors。`FAN_RENAME` 不受支持，因此其 OLD/NEW name records 不允许进入当前 receipt；V8/旧版 rename records 只能历史解码。

对象关联使用独立 `f8-fanotify-object-join-v1`：`{schema,attempt_id,group_id,group_seq,object_ref,marked_parent_refs,join_basis}`。permission group 必须有由 event-FD `fstat/statx` 唯一绑定的 `object_ref`，`marked_parent_refs=[]`；name group 必须有唯一 FID-derived `object_ref` 和由 DFID_NAME 解出的恰好 1 项 `marked_parent_refs`。target output object 若没有 parent/name/FID、handle/fsid/object generation 无法唯一关联，直接 incomplete，不允许将 parent refs 留 null。

FID name group 的 `FAN_NOFD` 必须按前述 group 分支接受；`FAN_Q_OVERFLOW`、PIDFD error/sentinel、permission group 非 FD 值、name group 非 `FAN_NOFD`、short read、未知字段、未知 event bit、sequence gap、PIDFD failure、重复/无匹配 row 或 mark inventory 漂移均为 incomplete。V8 event bytes 只可由 V8 decoder 历史读取，不能 cast 成上述 schema。

permission response 使用另一个 `f8-fanotify-action-v1`：`{schema,attempt_id,group_id,group_seq,event_fd_ref,response_raw_bytes_b64,response_write_ret,response_errno,event_fd_close_ret,event_fd_close_errno,actor_task_generation,operation_token_ref}`。它必须唯一回指 raw row；先完成 actor/object 核验，再写 exactly-once response，之后关闭 event FD 并保存结果。name group 不生成此 action row。

每个 event bit 的 info-record grammar、PIDFD 与 FID 绑定仍须通过 pinned UAPI conformance vectors 固化；`FAN_Q_OVERFLOW`、permission group 的负 metadata FD、short read、未知字段、未知 event bit、sequence gap、PIDFD failure、重复/无匹配 row 或 mark inventory 漂移均为 incomplete。`FAN_NOFD` 在 name/FID group 是规范值，只在 permission group 才代表缺失 event FD。V8 event bytes 只可由 V8 decoder 历史读取，不能 cast 成上述 schema。

## 4. cgroup-empty seal 与 final-fput observer 的硬边界

V16 §6 所描述的 `fd_install → file-cookie → __fput → fsnotify_close → FAN_CLOSE_WRITE` 仍只是目标 join，不是当前已证明的 kernel observer。为免“有字段即有证据”，任何将来实现必须输出 versioned row：

```text
f8-final-fput-observer-row-v1 = {schema,attempt_id,observer_profile_id,kernel_build_id,kernel_source_commit,hook_id,hook_seq,monotonic_ns,task_generation,fd_number,fd_generation,open_token_ref,file_cookie_digest,object_ref,event_kind,raw_args_digest,raw_return,loss_epoch,producer_lost,buffer_overrun,sequence_gap,reader_lag}
```

允许的 `event_kind` 只为 `fd_install_entry|__fput_entry|fsnotify_close|__fput_return`。每个字段必须来自版本化 observer ABI 和对应 raw source，不可由 userspace 推断补填；`loss_epoch` 必须含每个 producer/CPU 的 epoch identity 与可审计计数器。最终机械 join 必须按 V16 §6 顺序验证 open cookie lineage、最后 close、fput/refcount、fsnotify_close、fanotify close-write、directory/object generation、attempt 与 cgroup-empty refs，且所有 loss/gap 均为 0。

当前仓库没有 observer source、具体内核 build/source pin、hook/参数 ABI 证明、可构建的 collector、buffer loss implementation、raw observer rows 或机械 join 实现。因此此 schema 只是待实现接口；**final close 仍是 hard blocker**，不得以 ptrace syscall exit、fanotify `EAGAIN`、合成测试或静态文档声称 output closed/sealed。

## 5. 尚未关闭的 readiness blockers 与授权边界

runtime-ready 仍为 false，直到同时入库并独立验证：完整 native x86-64 syscall number universe/holes 与逐号 disposition/predicate artifact；固定内核的 `orig_rax=-1` side-effect-free conformance；上述 trusted trampoline/launcher/cgroup/census receipt 实现；fanotify 两组 init、directory-mark、permission/event-FD 与 raw parser conformance；copy-out permission profile；本版 final-fput observer ABI/source/build/loss implementation；可信签名 verifier；以及真实且独立可信的 F8 15-case evidence。

本版只修订静态文件。没有运行 launcher/trampoline、创建 cgroup/mount/mark、探测 capability/filesystem/kernel、调用 sudo、读生产输出/HDF5/PART/BI4，或启动 GenCase/native/solver/worker/GPU/queue；没有更改 gate、registry、ledger、denominator、T1/T2 或 qualification credit。用户对探索的总授权不替代这些明确的运行时/权限门槛。
