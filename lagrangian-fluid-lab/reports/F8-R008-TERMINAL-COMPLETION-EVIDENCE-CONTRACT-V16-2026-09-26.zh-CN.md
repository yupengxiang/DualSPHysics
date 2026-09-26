# F8 R008 Terminal Completion Evidence Contract v16

**状态：**仅设计修订、diagnostic-only；不是 supervisor / kernel monitor / syscall policy 的实现或 readiness 证明。V15 经 Terra High 配置只读复核为 `REVISE`、无 P0，模型身份未获 attestation。V16 修订 supersession、dummy-syscall synthetic return、trusted process lineage/census、预置 placeholder pool、fanotify UAPI profile 与 final-fput cookie/refcount 关联；未关闭的完整逐号 syscall package 和 runtime observers 仍使 `runtime-readiness=false`。

## 0. 版本效力矩阵与唯一当前解释

V16 §§1–7 是本 F8 terminal-completion subsystem 唯一有效的 syscall/output-FD/fanotify/census/copy-out/final-close 操作合同。旧版本保持不可变历史记录，不与 V16 的操作语义并行生效：

| 历史部分 | 处理方式 |
|---|---|
| V3–V7 的 terminal timestep/SaveData、fresh-run、签名/trust、BI4/RunPARTs 科学语义、output inventory、read-only seal 与 zero-credit 边界 | 保持有效；其中任何 syscall interception/watcher/actor/order 实现细节由 V16 §§2–7 取代 |
| V8 §1 的 permission/name group 与 event schema | 原事件字节作为历史格式；group flags、mark/mask、actor、event-FD、event info requirements 一律由 V16 §5 取代 |
| V9 §§1–4 的 syscall/fanotify wire/closure/ordering 操作规则 | 由 V16 §§2–7 取代；V16 不以旧记录 schema 代替当前 schema |
| V10 §1 fresh-create/append-only 文件行为及 §3 eager symbol binding | 继续有效；§2 syscall/fanotify closure、§4 census 和 §5 `FAN_ONDIR` 细节由 V16 §§3、5 取代 |
| V11 §1–2 的 broker/target-FD 与 virtual-map 实施条款 | broker、seccomp、ADDFD、target real output FD 机制废止；map 分类以 V13 §4 为准 |
| V12 §§1–3 的 ADDFD/FD allowlist/native output FD/broker-response mechanics | 全部废止；V12 §4 map 分类仅由 V13 §4 继承 |
| V13 §§1–3 的 io arbiter、global dispatch order 与 syscall policy mechanics | 由 V16 §§1–3、5、7 取代；V13 §4 的 disjoint `initial_maps_snapshot`/raw-row partition 数据模型保留，但快照 census/读取条件改用 V16 §3 |
| V14 §§1–4 的 gate、ptrace/seccomp、fanotify、syscall-table clauses | 全部由 V16 §§1–7 取代；V14 §5 的 bounded `/proc/maps` raw capture data fields 保留，task/census preconditions 改用 V16 §3；V14 §6 的 no-execution/authority fence 保持有效 |
| V15 §§1–6 的 token、`PTRACE_SYSEMU`、copy ABI、virtual-FD、fanotify、fput clauses | 全部由 V16 §§1–6 取代；V15 §7 的 complete syscall-package hard precondition及 §8 authority fence保持有效 |

明确不兼容规则：有效 profile **没有** `SECCOMP_RET_USER_NOTIF`、`SECCOMP_USER_NOTIF_FLAG_CONTINUE`、`SECCOMP_IOCTL_NOTIF_ADDFD`、`pidfd_getfd` broker duplicate、target real output FD/native allowlist、`PTRACE_SYSEMU` emulation path、跨 fanotify group global order。遇到其中任一项，V16 profile 不适用；不能把旧字段映射成当前通过证据。

## 1. Token subtype、causal parents 与允许阶段

token 是 supervisor 内部 gate state，不是 caller self-claim。exact schema 为 `{schema,attempt_id,token_id,token_kind,operation_subtype,task_census_epoch,operation_seq,target_task_ref,target_syscall_entry_seq,virtual_fd_generation,object_id,causal_parent_refs,phase,record_seq,previous_phase}`。

- `token_kind=target_syscall` 时，`operation_subtype=broker_io|virtual_fd_lifecycle|deny`；`target_task_ref={pid,pid_start_ticks,tid,tid_start_ticks}`、`target_syscall_entry_seq` 非 null；`operation_seq=null`；`causal_parent_refs=[]`。
- `token_kind=supervisor_operation` 时，`operation_subtype=terminal_fd_close|output_seal|verifier_read|supervisor_copy`；target identity/syscall sequence 为 null，`operation_seq` 为非零连续整数，`causal_parent_refs` 是按 `(ref_kind,ref_id)` 排序唯一的既有 `target_syscall|supervisor_operation|terminal_exit|census_epoch` refs。`terminal_fd_close` 必须有已验证 `terminal_exit` 与该 object 所有最后写 token；`output_seal` 必须以前置 `cgroup_empty` 与全部 `terminal_fd_close` refs 为 parent；无父项的 terminal/seal operation 无效。
- 精确状态集合按 subtype 冻结。`broker_io|virtual_fd_lifecycle|deny` 仅允许 `ENTRY_STOP → CENSUS_FROZEN → TOKEN_HELD → ARGS_CAPTURED → SIDE_EFFECT_OR_DENY → SUPPRESSED_SYSCALL_EXIT_VERIFIED → RESPONSE_REGS_VERIFIED → EVENT_JOINED → TOKEN_RELEASED`；`terminal_fd_close` 只允许 `TERMINAL_EXIT_VERIFIED → ALL_WRITER_TASKS_GONE → CLOSE_TOKEN_HELD → CLOSE_SYSCALL_EXIT_VERIFIED → FINAL_FPUT_JOINED → FANOTIFY_JOINED → TOKEN_RELEASED`；`output_seal|verifier_read|supervisor_copy` 各有单独 versioned phase array，不能借用 target syscall 的必填字段/阶段。

单线程 supervisor 一次至多一个 live output token。每次迁移保存 raw request/result、actor generation、状态前后值、因果 refs、单调 journal seq、完整 hash-bound payload 与 verifier 可重算的 digest。token 缺口、并发/重入、错误 parent、未知 subtype/phase、event/journal loss 或状态重放不一致即 incomplete/open。

## 2. x86-64 syscall suppression 与 synthetic return 的可重放过程

本 profile 只接受 native x86-64、固定 kernel source/build、无 inherited/installed seccomp filter、全 tracee 首条用户态指令前 `PTRACE_SEIZE` 的 profile。syscall-stop 由 `PTRACE_O_TRACESYSGOOD` 与 `PTRACE_GET_SYSCALL_INFO.op` 确认。所有 `waitpid` 原始 status、`NT_PRSTATUS` 原始寄存器 bytes、`PTRACE_GET_SYSCALL_INFO` bytes、ptrace request/argument/return/errno 与 task generation 都逐条 journal；遇到 `PTRACE_EVENT_SECCOMP`、未知 stop、lost stop 即拒绝。

**deny 与 broker-emulated syscall 使用同一 suppression ABI**：

1. 在 `SYSCALL_INFO_ENTRY` 停止点保存完整 `user_regs_struct`。native ABI entry 必须与 syscall-number row 一致；记录 `orig_rax=nr`、entry `rax`、六参数寄存器、IP/SP 与 audit arch。完成 task census、参数 copy-in、broker operation/copy-out 和所需 fanotify joins 时 tracee 仍停住。
2. supervisor 用 `PTRACE_SETREGSET(NT_PRSTATUS)` 将 `orig_rax` 改成 x86-64 signed `-1`（two's-complement 全 1），其余 registers 原样保持；立即 `PTRACE_GETREGSET` readback，全结构逐字节相等（除允许修改字段外）才可继续。该 invalid syscall sentinel 由固定 kernel source profile 证明不会分派到任何 syscall handler。
3. 使用 `PTRACE_SYSCALL` 恢复这一个 TID，要求且仅接受紧接的 `SYSCALL_INFO_EXIT`：kernel dummy sentinel result 必须是 `rval=-ENOSYS,is_error=1`，`rax=-ENOSYS,orig_rax=-1`；SIGKILL、signal/event/exec/task death、缺少 stop、其他 nr/result 均令已做的 broker side effect 留在本次 incomplete attempt，不重试。
4. 在这个 exit-stop 上，将 `rax` 写成精确返回值：拒绝路径写冻结 errno 的负值；broker path 写实际 broker syscall return count/FD/offset。保存完整 register-write bytes、ptrace 返回值与 readback；entry args、sentinel dummy result、emulated result 分列记录，绝不将 dummy `-ENOSYS` 伪称为 original kernel syscall result。只有全部核验成功才 release token，再 `PTRACE_SYSCALL` 恢复 tracee；寄存器在 syscall-exit-stop 的 verified `rax` 是它返回用户态前看到的 ABI result。
5. exit-stop 之后发生的 signal-delivery/group-stop 按 tracee 原始 `siginfo`、`PTRACE_EVENT_STOP`、`PTRACE_LISTEN`/signal injection 记录；不能回填或改写已完成 syscall result。真实 pass-through 的 `allow_nonoutput_proven` syscall 不改 `orig_rax`，执行实际 kernel syscall，并保留真实 entry/exit 与 `-ERESTART*`/signal/restart_syscall 每一跳。synthetic sentinel transaction 禁止 `PTRACE_SYSEMU`、二次原 syscall entry、restart retry 或任何 output syscall pass-through。

Linux ptrace ABI/stop ordering 见 [ptrace(2)](https://man7.org/linux/man-pages/man2/ptrace.2.html)；完整 profile 仍须对确切 kernel source/build 证明普通 entry-stop 中 `orig_rax=-1` 的行为、sentinel 无 side effect 与 exit-stop result，并包含可重放 emulator conformance vectors。在本实现/向量入库前 `runtime-readiness=false`。

## 3. Trusted lineage、cgroup epoch 与 task/mm/files census

不靠 pairwise `kcmp` 自己发现全体 peer。根闭包来自 trusted launcher：它在 host 初始 PID namespace 创建独立 child（root child 的 `mm_struct` 与 `files_struct` 不与 launcher/ancestor 共享），将 child 放进专属 cgroup-v2 leaf，held pidfd、start ticks、parent lineage、PID namespace inode、host proc mount identity、完整 inherited FD inventory 与 `KCMP_VM/KCMP_FILES` negative comparison 一起写入 `root_launch_record`。目标 user code 在 lineage/ptrace/cgroup policy 固定之前不能执行；`setns/unshare/namespace clone`、cgroup migration、FD passing、`CLONE_UNTRACED`、未列 clone flags 与脱离 cgroup 操作均被 syscall policy 拒绝。

ptrace birth closure 使用 `PTRACE_O_TRACECLONE|TRACEFORK|TRACEVFORK|TRACEEXEC|TRACEEXIT|EXITKILL`：每个允许的 child 在首条 user instruction 前取得 child stop、event message/flags、pidfd 或 PID+start-ticks generation，并进入 census epoch；未知/无法取得初始 stop 的 child 立即 fail. 本 R008 profile 默认 deny process fork/vfork/exec 与任何非冻结线程 clone；支持的 thread clone flags 在完整六参数 row 中枚举，且新 TID 在 parent 恢复前完成 `kcmp(KCMP_VM)`、`kcmp(KCMP_FILES)`、FD-table generation 与 cgroup membership binding。任何可创建共享 `mm` 或 `files_struct` 的主体因此必须属于 launcher/ptrace tracee lineage；不存在由外部 task 在两个 `/proc` 扫描之间悄然创建共享 peer 的可接受路径。

每个 census epoch 用 cgroup-v2 `cgroup.freeze=1` 和 readback `frozen 1` 冻结 lineage，再读取同一个 held host-proc/cgroup FD set；双向枚举全部 `cgroup.procs`、每个 `/proc/<pid>/task`、pidfd/start ticks、`/proc/<tid>/stat` 原 bytes、`fdinfo` 和 `KCMP_VM/FILES` pair results。inventory 前后 digest、parent lineage、birth/exit event sequence、cgroup membership 与 proc PID namespace source 必须闭合；随后只 `PTRACE_INTERRUPT`/resume 被授权的单 TID，并保持其余同 `mm_id` **或**同 `files_table_id` peer stopped。任何 proc view hidepid/incomplete、权限拒绝、PID reuse、无法证明 target 与 launcher initial mm/files 隔离、task birth/exit race、cgroup migration、census digest 变化，都 fail closed。

target `PR_SET_DUMPABLE=0` 在首条 user instruction 前由 trusted launcher 设置，raw prctl args/result/cred 与后续 target `prctl` policy 绑定；target 后续不得重新打开 dumpability。supervisor/tracee credentials、user-namespace、effective/permitted capability 与 `ptrace_may_access` 来源记录入 profile。host root / 具备 `CAP_SYS_PTRACE` 的恶意管理员不在本 security claim 内；若威胁模型包含该主体，则所有外部-memory exclusion/copy-out claim disabled，readiness false。`kcmp` 的 permission rule 参见 [kcmp(2)](https://man7.org/linux/man-pages/man2/kcmp.2.html)。

`initial_maps_snapshot` 复用 V13 disjoint raw-row schema；只允许在同 `mm_id` task 全 stopped 的固定 epoch 对同一 held `/proc/<pid>/maps` FD 有界顺序读取至 EOF，并记录每个 read、EOF、total bytes 与 epoch digest。V14 §5 的 raw bytes/parse/typed-ref rules 继续有效，但必须附本节 root-lineage/census stop proof。short/error/epoch change/unknown mapping mutator/userfaultfd state 即 open/missing。

Copy ABI 在每个 profile 中必须预先固定为 `supervisor_process_vm` 或 `supervisor_ptrace_word` 一个值。前者只授权该已 attach supervisor 对该 pidfd/start-ticks target 发起 `process_vm_readv/writev`，target 自行 syscall 始终 deny；launcher 必须固定 target 不可 dumpable、 supervisor PTRACE access check/credentials/capabilities、remote iovec/VMA bounds、每段 bytes/hash/short-count/errno。后者只授权同一 tracer 的按 native-word `PTRACE_PEEKDATA/POKEDATA`，每个 word 地址/原值/新值/errno 全部记录。启动前 scratch conformance 必须验证权限与 byte-exact copy，未通过不得建立 attempt。共享 mm/files tasks 均 stopped、目标 VMA 为已验证 private-anonymous/no userfaultfd、span 完整、external untrusted `CAP_SYS_PTRACE` writer 排除时才 copy；否则拒绝 synthetic read/fstat/getdents 等 result。

## 4. Pre-exec placeholder pool 与完整 virtual-FD 编号模型

由于禁止 ADDFD，virtual open 必须返回一个 kernel 中确实预存在的 inert descriptor number。trusted launcher 在 exec 前构造固定 `placeholder_pool`：对 manifest 中每个唯一高 FD slot `N`，用 `posix_spawn_file_actions_adddup2`（或 profile 唯一指定的等价 raw `dup2`）将 held `/dev/null` descriptor 复制至 exact `N`；flags、source dev/inode/mount、target FD result、`RLIMIT_NOFILE`、inherited input/control FDs、`FD_CLOEXEC=0` 与 `files_struct` identity 均原始记录。所有 pool FD 在第一条 target instruction 前已 open、处于 virtual-free 状态；缺 slot/冲突/identity mismatch 禁止 exec。pool 是有限容量，冻结 max logical descriptors；达到上限时只合成 ABI 正确 `EMFILE`，不能临时增加 kernel FD。

target 的所有 syscall 以 ptrace entry stop 截获；所有进入 pool 区间的 descriptor call 都 broker-emulate 或 deny。成功的 virtual `open/openat/creat` 由 supervisor 分配一个已存在且当前 virtual-free 的 physical placeholder slot，登记 `(files_table_id,fd_number,fd_generation,virtual_ofd_id,object_id,open_flags,virtual_offset,cloexec,state)`，并按 §2 返回该准确 FD number；kernel FD table 不发生 open/dup。`dup/dup2/dup3` 均由 supervisor仅修改 virtual table、合成 POSIX 返回值；`close/close_range` 只标记 logical slot free/advance generation，底层 placeholder 一直保持 open 到 target exit。`fork/vfork/exec` 被 synthetic deny；thread clone 仅限绑定的 CLONE_VM/FILES/SIGHAND/THREAD profile，virtual table 依据实测 `KCMP_FILES` relation 在同一个 `files_table_id` 共享。

每次分配/复用都有 monotonic generation；旧 generation 迟到引用 deny。`getdents64(/proc/self/fd)`、readlink/proc-fd、F_GETFD/F_GETFL、stat、poll/epoll/ioctl、mmap、SCM_RIGHTS、pidfd_getfd、io_uring、splice/copy_file_range/vmsplice/sendfile、lock/xattr/metadata 等若没有逐号 exact virtual semantics 一律 deny，不能落到底层 `/dev/null` 行为。目标若以任何未拦截 syscall 访问 placeholder，profile failure。全部真实 output file descriptor/OFD 仅在单线程 supervisor：每个 output inode 仅一个 writable backing OFD；logical open-description 的 offset/status/append semantics 在 virtual table 中独立维护，由 supervisor `pread/pwrite` 与 serialized size sampling 实现。任何 dup、temporary handle、supervisor alias 会使该 one-backing-OFD invariant 无法证明时拒绝该对象。

## 5. Fanotify group UAPI、scope、mask 与 event-FD exact rules

输出只允许一个 dedicated fresh tmpfs mount，mount namespace private、no bind/remount/alias；marks 覆盖此唯一 mount（不是含有其他项目数据的宿主 mount）。两个 groups 都以 `fanotify_init(FAN_CLOEXEC|FAN_NONBLOCK|...)` 建立；raw `fanotify_mark.flags` 精确为 `FAN_MARK_ADD|FAN_MARK_MOUNT|FAN_MARK_ONLYDIR`，其中 `FAN_MARK_MOUNT` 是 mark-scope bit、`FAN_MARK_ONLYDIR` 限制 held root 必须为 directory，mount/root FD 身份绑定。`FAN_ONDIR` 只作为 event mask bit，绝不写入 mark flags。任一 unsupported flag/filesystem/layout/permission 失败即不启动 attempt。

| 字段 | permission group | name/notification group |
|---|---|---|
| init flags | `FAN_CLASS_CONTENT|FAN_REPORT_PIDFD|FAN_CLOEXEC|FAN_NONBLOCK`；无 FID/name/TID report | `FAN_CLASS_NOTIF|FAN_REPORT_PIDFD|FAN_REPORT_DFID_NAME_TARGET|FAN_CLOEXEC|FAN_NONBLOCK`；无 permission bits/TID report |
| event-f_flags | 精确 `O_RDONLY|O_CLOEXEC|O_LARGEFILE` | kernel FID mode：`metadata.fd=FAN_NOFD` |
| mark mask | `(FAN_OPEN_PERM|FAN_ACCESS_PERM|FAN_OPEN_EXEC_PERM)|FAN_EVENT_ON_CHILD|FAN_ONDIR` | `(FAN_CREATE|FAN_DELETE|FAN_DELETE_SELF|FAN_MOVE|FAN_MODIFY|FAN_CLOSE_WRITE|FAN_ATTRIB|FAN_OPEN|FAN_ACCESS|FAN_CLOSE_NOWRITE|FAN_RENAME)|FAN_EVENT_ON_CHILD|FAN_ONDIR` |
| actor/object join | process PIDFD + exact supervisor generation + event-object `fstat/statx` | PIDFD + FID/name record + mount/fsid + object generation |

`name_group` event-info profile 对每个单 event bit 有 exact sorted row：PIDFD required；`FAN_RENAME` required `FID+OLD_DFID_NAME+NEW_DFID_NAME`；create/delete/move required target FID+DFID_NAME；其他 path events（明确包括 `FAN_CLOSE_WRITE`）required FID+DFID_NAME；no optional substitution/trailing record。raw metadata version/length/reserved、每个 info header/type/length/padding/payload、FID/FSID/file-handle/name bytes 按冻结 UAPI 重解析。V8 的上述 FID/name grammar保持字段格式有效，但本节 mask/scope/actor 取代 V8/V9 旧语义。

permission responder 为单线程且是唯一 group queue reader/responder。`FAN_OPEN_PERM/FAN_ACCESS_PERM/FAN_OPEN_EXEC_PERM` 的每个 raw metadata 行必须含 nonnegative event `metadata.fd` 和 PIDFD info；它是独立 `O_RDONLY` event OFD，不是 supervisor output backing OFD。Responder 只能 `fstat/statx` 识别 mount/dev/inode，再向 permission group 写唯一 response（`response.fd` 原整数），紧接着恰好 close event FD 并记录 close result；event FD 不得转交、fork/inherit、写入或读取内容。对于 supervisor 自身 open，PIDFD/单线程 identity 必须等于 supervisor（`pid==tid`），operation/token/path/object 来自 authenticated IPC request；不能把该 event 误标 writer/target。open syscall 在 response 和 event-FD close 成功前不能返回。`FAN_REPORT_TID` 与 `FAN_REPORT_PIDFD` 不兼容，当前 profile 不启用 TID 报告；单线程 event actor 由 PIDFD 与 task census共同证实。event FD/permission UAPI 参见 [fanotify(7)](https://man7.org/linux/man-pages/man7/fanotify.7.html)、[fanotify_init(2)](https://man7.org/linux/man-pages/man2/fanotify_init.2.html)。

per-group sequence/drain 分开记录，不声称跨 queue enqueue 全序。FID group 的每个 `FAN_CLOSE_WRITE` event 必须唯一 join 至 close token/object generation；跨 token event merge、`FAN_Q_OVERFLOW`、`FAN_NOFD`、short read、未知 mask、event-FD 泄漏、PIDFD failure、duplicate/unmatched response 均 incomplete。每 group drain=EAGAIN 仅为该 queue observation，不替代 final-fput join。

## 6. 唯一 backing OFD 与 final-fput/file-cookie lifecycle

在受支持 profile 中，每个 output inode 恰好一个 supervisor writable backing OFD；virtual handles 不创建真实 duplicates，使用 position-explicit `pread/pwrite` 和 per-virtual-OFD logical offset/append state。禁止 backing-FD `dup*`、`pidfd_getfd`、`SCM_RIGHTS`、fork/inherit、supervisor worker thread duplicate 与不受支持 VFS operation。`FAN_OPEN_PERM` event-FD 是另一个 O_RDONLY open description，不是 backing OFD。terminal writer exit 后需先证明所有 logical virtual descriptors closed、target lineage `cgroup.events populated 0/frozen state` 和无 output request 在途，才可开始 final backing close。

kernel observer profile 为 backing OFD 建立不可歧义 cookie mapping。唯一受支持 hook 是 pin 到精确 kernel build/source hash 的 `fd_install` entry；若该 hook/参数 ABI不可捕获则本 profile 不支持（不得临时替换为未列 hook）。每个 row 精确绑定 supervisor pid/tid generation、`fd_number+fd_generation`、open token、mount/dev/inode/object_id、`struct file *` opaque keyed digest；map key 为内核指针仅在内核内使用。pointer-generation 单调分配，`fd_install` 的 map insert 必须是 absent；`__fput` return 后 observer 标记 cookie retired 并删除 pointer key；任何 active pointer collision、未退休重用、map update failure 都是 loss。不得将原始 kernel pointer 当作 inode/object ID。

对 terminal close，entry/return/callsite observer 保存 `{cookie,file_generation,object_id,fd_generation,close_token,hook_id,hook_seq,actor_pid/tid_generation,source_build_hash,lost_total}`。在 pinned kernel source 中证明 `__fput(file)` 为最后引用的最终清理、同一 file 参数到 `fsnotify_close(file)` 的 callsite 顺序，以及 `FAN_CLOSE_WRITE` enqueue 对应此 writable OFD。observer 在 open install 到 final return 的全窗口 continuous；单线程 event loop 无 backing OFD aliases，其他 target tasks不持有该 `struct file`，queued permission event-FDs 使用独立 O_RDONLY OFD。monitor buffer non-overwrite、bounded max concurrent object/FDS；producer sequence连续，lost/overflow/reserve-failure=0，event reader在 close wait期间不中断。

机械 join 仅接受：`terminal_exit_ref + final-write token refs → supervisor close syscall entry/exit(fd_generation) → fd_install cookie lineage → __fput.entry(cookie) → fsnotify_close(file,cookie) → __fput.return(cookie) → name_group FAN_CLOSE_WRITE(FID,mount/fsid/object-generation)`，然后该 group 逐项排空且 observer loss counters=0。文件系统不能给出稳定 handle/object-generation、任一 row 不能唯一对应 cookie，或没有 pinned hook/source/ABI implementation 时不声称 final close；attempt 保持 open/missing。源码中 deferred final-fput 的存在由 pinned kernel source adjudicate；syscall exit 或 EAGAIN drain 不能单独完成 join。

## 7. 不因文档而伪称 runtime-ready

版本化 artifact package 仍必须包含完整 native x86-64 UAPI number universe/holes、source commit与header bytes/hash、逐号六 ABI words/layout、每号唯一 disposition/handler、virtual-FD/path/memory predicates DSL、allow proofs、generator/生成物 hashes、exact fanotify UAPI rows、ptrace suppression conformance vectors、trusted launcher/census receipts schema、copyout permission profile 与 final-fput observer source/ABI/loss model。target `ptrace/process_vm_*/userfaultfd/bpf/perf/mount/setns/ioctl/io_uring/FD passing` 等所有号码逐条 deny 或 exact broker model；默认 deny。V16 没有这些 executable artifacts，也未实现/测试任何 kernel observer，因此 `runtime-readiness=false` 恒成立；不能将 V16/Python synthetic tests/主机上单个 generated header 当作 F8 runtime validation。

V16 只修订静态设计文档。未读生产 output/HDF5/PART/BI4，未做 root/sudo 或 host capability probe，未启动 GenCase/native/solver/worker/GPU/queue，未改 gate/registry/ledger/denominator/T1/T2/qualification credit。缺少 runtime implementation/profile 和真实可信 15-case evidence 仍是未完成事项。
