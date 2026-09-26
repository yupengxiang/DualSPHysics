# F8 R008 Terminal Completion Evidence Contract v15

**状态：**proposal-only、diagnostic-only；不实现 supervisor、tracer、broker、fanotify observer 或 verifier，不改变 F8 readiness/qualification/gate/registry/ledger/分母/credit。V14 经 Terra High 配置只读审查为 `REVISE`、无 P0，reviewer 未 attestate 模型身份。V14 已正确禁止 USER_NOTIF、撤销跨 fanotify queue 全序声明并要求 final-fput evidence，但留下旧版本条款冲突、ptrace emulation 状态不完整、virtual-FD/files table closure、permission-event FD、observer join 和完整 mm census 缺口。V15 逐项补充；任何实现/运行 profile 仍须另行冻结并独立审查。

## 0. 明确 supersession 与保留边界

本版本只替换“如何执行/观察系统调用、输出 FD 与 fanotify 生命周期、任务/地址空间 census、copy-out 和 close attribution”的操作语义；不可变历史版本继续留档，但不得与当前规则并行解释。具体地：

1. V8 §1、V9 §§1–4、V10 §§1–2 中关于 syscall mediation、listener/profile、`continue_one`、target/broker entry/exit 和 fanotify order 的 operational requirements，由 V15 §§1–5 完整替换；未冲突的 raw event byte/schema 仅作为输入数据格式保留，不能保留旧的 authority/order 含义。
2. V11 §§1–3 与 V12 §§1–3 中所有 `SECCOMP_RET_USER_NOTIF`、notification ID/response、`SECCOMP_IOCTL_NOTIF_ADDFD`、`SECCOMP_ADDFD_FLAG_SEND/SETFD`、target real output-FD、broker `pidfd_getfd()` 临时 duplicate、native output-FD read/fstat/close 例外及旧 broker/responder actor 规则，全部废止，不得进入 V15 profile 或 evidence。对应字段可在历史 receipt 中出现，但 V15 verifier 将其标记为 legacy/untrusted 而非当前机制证据。
3. V12 §4 与 V13 §§1–4 的 FD arbiter、fanotify ordering、syscall disposition、task/copy-out 与 maps snapshot mechanics 由 V15 §§1–5 替换。V3–V7 中 output syscall/watcher mechanics 也仅在与本版本兼容时保留；RunPARTs/BI4/terminal SaveData、输入清单、签名信任链、output inventory/parser 和 read-only seal 的科学/内容语义继续有效。
4. 新 profile 的根规则是 **no seccomp USER_NOTIF, no ADDFD, no target real output FD, no pidfd_getfd broker duplicate**。任一遗留机制被观测到，当前 profile 不适用，attempt open/missing。

## 1. 唯一可信 writer gate 与精确 token schema

supervisor 是输出 root 唯一持有者。单线程 `io_supervisor` event loop 独占输出 root FD、真实 output FDs、virtual-FD table、target ptrace resume 权限和 broker filesystem calls。fanotify responder 是分离的最小权限进程，只持有 fanotify group FD、响应 IPC 与临时 event FD；没有输出 root FD，除已明确定义的只读 fanotify event-FD exception 外，不拥有输出对象 descriptor。

token schema 固定为 `{schema,attempt_id,io_token,token_kind,task_census_epoch,operation_id,phase,record_seq,target_task_ref,target_syscall_entry_seq,supervisor_operation_seq,caused_by_io_token,virtual_fd_generation,object_id,previous_phase}`。`token_kind` 仅为 `target_syscall|supervisor_operation`；前者要求 `target_task_ref={pid,pid_start_ticks,tid,tid_start_ticks}` 与 `target_syscall_entry_seq` 为非 null、`supervisor_operation_seq=null`、`caused_by_io_token=null`；后者要求 `target_task_ref=null`、`target_syscall_entry_seq=null` 且 `supervisor_operation_seq` 与 `caused_by_io_token` 为非 null。所有其他 conditional nullability 由版本化 schema 固定。`phase` 只能沿有向状态图单调迁移：

`ENTRY_STOP_VERIFIED → CENSUS_EPOCH_FROZEN → TOKEN_HELD → ARGS_CAPTURED → BROKER_EFFECTS_COMPLETE → COPYOUT_COMPLETE_OR_NONE → PTRACE_SYNTHETIC_RETURN_REGISTER_VERIFIED_OR_KERNEL_EXIT_VERIFIED → REQUIRED_FANOTIFY_AND_KERNEL_EVENTS_JOINED → TOKEN_RELEASED`。

唯一 event-loop thread 一次只能持有一个 token。发出 token 的条件是 raw stop、ABI、task census、FD generation 和所有输入 pointer bytes 均完成独立校验。目标相关 broker syscall、supervisor-only copy-in/copy-out、permission response 和 final close 通过 authenticated IPC 串行归属于该 token；event-loop 不能在任一阶段并行启动第二个 output effect。每一状态转换记录 previous/current state、monotonic journal seq、actor pid/tid generation、操作原始输入/结果及内容哈希；verifier 从 records 重建，调用方 bool 无效。异常、缺行、跳号、重入、死亡、丢失或未知 transition 均停止 attempt，不清理证据、不重试、不 seal。

## 2. Ptrace x86-64 emulation 状态机

实际 profile 只接受冻结的 native x86-64 Linux ABI 与 `PTRACE_GET_SYSCALL_INFO`；不接受 compat/x32。所有 tracee 在首条用户态指令前已 attach，设置 syscall-stop、clone/fork/vfork/exec/exit、`PTRACE_O_EXITKILL` 等冻结选项。每次 `waitpid` 原始状态均区分 `ENTRY`、`EXIT`、`SIGNAL_DELIVERY`、`PTRACE_EVENT_STOP`、exec/birth/exit event 与死亡；仅 `PTRACE_O_TRACESYSGOOD` 标记 syscall-stop，并以 `PTRACE_GET_SYSCALL_INFO.op` 判定方向。Seccomp filter/notification 在该 profile 中不存在；任何 `SECCOMP_RET_USER_NOTIF`/`PTRACE_EVENT_SECCOMP` stop 都是 profile violation。参见 [ptrace(2)](https://man7.org/linux/man-pages/man2/ptrace.2.html) 与 [seccomp(2)](https://man7.org/linux/man-pages/man2/seccomp.2.html)。

每个 syscall transaction 的精确转换如下：

| 条件/事件 | 必须动作 | 证据与下一状态 |
|---|---|---|
| `SYSCALL_INFO_ENTRY` | 保存完整 native `user_regs_struct`、`ptrace_syscall_info` 六参数、IP/SP、audit arch 和 stop ID；按冻结 syscall table 唯一分类 | `ENTRY_CAPTURED`；缺项/未知编号 deny |
| deny | 在 entry stop 直接调用 `PTRACE_SYSEMU` 跳过原 syscall；设置 ABI 返回寄存器为固定负 errno 并 readback；不得继续到 kernel syscall body | `SYNTHETIC_DENY`，journal 明确 `kernel_effect=false`，resume 原 signal-delivery 规则 |
| broker emulation | acquire token；freeze census；完整 capture pointed input；supervisor 执行 broker effect；写目标 output buffer（如有）；将 x86-64 `rax` 设为 exact signed syscall result，保存 `PTRACE_SETREGSET(NT_PRSTATUS)` raw bytes 并 readback；完成 event joins 后 release token，再调用 `PTRACE_SYSEMU` 跳过原 syscall | `SYNTHETIC_RETURN`；`PTRACE_SYSEMU` 路径没有 syscall-exit stop，不得伪造 kernel exit。return 只可由 verified register write 与后续 syscall/user-state record 证明 |
| `allow_nonoutput_proven` | 只有对应逐号参数 predicate proof 通过时用 `PTRACE_SYSCALL` 执行真实 syscall；读取真实 `SYSCALL_INFO_EXIT` 与寄存器 | `KERNEL_EXIT`；entry/exit 配对，否则 incomplete |
| signal/group-stop | 在 token 外完整记录 `PTRACE_GETSIGINFO`/event/message；只允许按 profile 原样注入 signal；`PTRACE_EVENT_STOP` 依 seized tracee 的 group-stop 规则进入 `PTRACE_LISTEN` 或 fail closed | signal stop 不是 syscall exit；不得用信号事件补 syscall result |
| broker token 活跃时 SIGKILL、异步致命 signal、意外 ptrace event、tracee 消失或 register readback mismatch | 不尝试合成成功结果/重试；停止 attempt 并保留 partial output | `INCOMPLETE_OPEN` |
| 真实 syscall 返回 `-ERESTART*` 或 libc/kernel restart sequence | 保留真实 exit bytes；后续 signal stop、`restart_syscall` 或重新 entry 按新 stop ID 显式链接；不得折叠掉重启次数 | 仅原样记录内核实际路径 |

`PTRACE_SYSEMU` 的受支持架构/行为必须由实际 profile 对应的 kernel source/build 证明；它仅用于跳过 syscall，不代表内核产生 exit stop。完成 broker effects 与所有所需 event joins 后，supervisor 在 tracee 仍停于 syscall-entry stop 时将精确返回值写入 x86-64 `rax`，保存 `PTRACE_SETREGSET(NT_PRSTATUS)` raw bytes 并 readback；随后释放 token，再 resume tracee。因为每个 tracee 都以 `PTRACE_SYSEMU` 等待下一次 syscall entry，原 syscall不会在 token 外执行。register write syscall/ABI、`orig_rax`/`rax` entry semantics、signal 注入和 skipped-call 返回寄存器均须有 pinned source profile 与离线 emulator conformance vectors；未完成前 runtime-readiness=false。禁止用“下一 stop 正好是 exit”假设取代上述状态区分。Linux ptrace 文档说明 `PTRACE_SYSEMU` 不执行 syscall、且没有 syscall-exit stop；V15 据此将 synthetic return 与真实 kernel exit 分成不同状态。

## 3. Census、共享 `files_struct` 与 copy-out ABI

`KCMP_VM`/`KCMP_FILES` 是对已给定任务 pair 的比较，不是共享关系枚举器。可接受的 census 要求 trusted launcher 提供 host 初始 PID namespace 中的完整 procfs 视图、PID reuse 绑定与足够 ptrace 权限；逐个枚举 census epoch 内所有 visible process、每个 `/proc/<tgid>/task` TID，记录原始目录项、`/proc/<pid>/stat` start time、pidfd（可取得者）及 candidate birth/death。随后对每个候选 task 与 tracee set 逐 pair 调用并记录 `kcmp(KCMP_VM)` 与 `kcmp(KCMP_FILES)` 结果/errno/权限。两次全量 task inventory 与 epoch 开始/结束边界必须一致；任何权限拒绝、PID namespace/procfs 不完整、短读、任务变化或无法解释的 kcmp 结果都使 census open/missing。`kcmp` 权限限制按 [kcmp(2)](https://man7.org/linux/man-pages/man2/kcmp.2.html) 处理，不以“数目相同”代替对象枚举。

在每个 output token 和每次 copy-out 前，ptrace-stop **所有与目标共享 `mm_id` 或 `files_table_id` 的 task**，并复核 pidfd/start-time 与两个完整 task inventory 的 epoch digest；只停同 `mm` peers 不足以封闭跨地址空间共享 `files_struct` 的 FD slot race。clone/fork 事件先停子任务再新开 census epoch；不能发现、停止或复验新 task，立即 incomplete。

copy ABI 每个 profile 必须在 `supervisor_process_vm` 或 `supervisor_ptrace_word` 两种精确 schema 中预先选定一种；同一 attempt 不得切换。前者唯一允许 supervisor 发起 `process_vm_readv/process_vm_writev`，target 自行发起的这两个 syscall 一律 deny；后者只允许 supervisor 的 `PTRACE_PEEKDATA/POKEDATA` 固定 word-size 序列。supervisor 在同 mm 与 files-table peers 全部停止、target `PR_SET_DUMPABLE=0` 且未授权外部 `CAP_SYS_PTRACE` writer 的条件下，先按完整 VMA snapshot 校验 pointer span，随后逐 segment bounded-copy；每个 syscall 保存 supervisor PID/TID generation、远端 pidfd/start time、local/remote iovec 或 ptrace word bytes/hash、返回 byte count/errno、VMA raw row IDs 与 token。全部结果按 target ABI 对应的 read/fstat/getdents/etc layout 编码；partial copy、hole、non-private/shared/file-backed mapping、userfaultfd/registration uncertainty 或不受信任外部 ptrace writer 条件不成立，一律 incomplete。supervisor copy-out syscall 是特权进程内部 operation，不是 target syscall disposition 的例外。

安全边界需明示：`PR_SET_DUMPABLE=0` 和 task census 不阻止 host root/具备相关 capability 的恶意管理员。本 profile 将此类主体列为可信主机边界；若威胁模型要求抵御 host administrator，就必须拒绝 process-memory copy-out，不得宣称本机制提供该保证。

## 4. Virtual-FD 与 descriptor table 全闭包

target 输出 FD slot 只能映射到 exec 前由 trusted launcher 预置的有限 `placeholder_pool`：每个成员是固定 FD number 和精确 hash-bound identity 的 inert `/dev/null`（或同等已冻结 inert FD），从不指向 output inode/OFD。startup descriptor inventory 必须逐个证明 pool 完整、不可被别的 actor 关闭/替换，初始空闲；pool 上限与 `RLIMIT_NOFILE` 一起冻结。运行期 `open/dup/dup2/dup3` 均由 `PTRACE_SYSEMU` 跳过，supervisor 仅选择一个当前 virtual-free 的已预置 FD number、更新 virtual table/generation 并合成返回；`close/close_range` 只更新 virtual state，底层 placeholder 继续保持打开且不可由 tracee syscall 操作。池耗尽时按冻结 ABI 合成 `EMFILE` 或 fail closed；不得在 token 外分配新 kernel FD。

virtual table row 固定 `{pid/tid_namespace_generation,files_table_id,fd_number,fd_generation,virtual_ofd_id,object_id,open_flags,virtual_offset,cloexec,refcount,state}`。编号分配只从上文 pool 在全量 table census 后选择；close 后 generation 单调增加，任何迟到的旧 generation 使用立即 deny。dup alias 指向同一 `virtual_ofd_id`；单独 open 创建新 virtual OFD/offset。fork/vfork、SCM_RIGHTS、pidfd_getfd、未建模的 clone flags、exec 继承、ioctl、mmap、poll/epoll/io_uring、sendfile/splice/vmsplice/copy_file_range、F_SETFL/record locks 等没有精确 handler 的操作逐号 deny；只有版本化 profile 明确实现且有 synthetic conformance tests 的操作才 broker-emulate。虽有 kernel placeholder slot，但其直接 read/write/stat/seek 等任何 syscall 均须按 virtual table 拦截或拒绝；无 handler 时不得让 syscall 落到 placeholder object。

所有真实 output FD 和真实 open-file description 仅由单线程 supervisor 持有。对 virtual `read/write/pread/pwrite/lseek/fstat` 等 operation，supervisor 从 output object 使用 position-explicit `pread/pwrite`，独立维护 virtual OFD cursor、append/short-write/error 语义，捕获精确输入与结果，再按 §3 copy ABI 合成 target return。不得依靠目标 placeholder 的内核行为来模拟输出。共享 `files_struct` task 全量停顿；若一个编号/alias 可能从未盘点的 task、FD transfer、inherited descriptor 或未实现 syscall 抵达，则 fail closed。

## 5. Fanotify UAPI 与 temporary event-FD lifecycle

保留 V8 双 group 分离原则，并用 V15 exact profile 替换 V8/V9/V12 旧 mask/actor 文句：

- `permission_group`：`FAN_CLASS_CONTENT|FAN_CLOEXEC|FAN_NONBLOCK|FAN_REPORT_PIDFD`，不得启用 FID/name/TID report flags，标记精确输出 mount 上的 `FAN_OPEN_PERM|FAN_ACCESS_PERM|FAN_OPEN_EXEC_PERM`。profile 固定 kernel/UAPI、mark type/flags、event_f_flags=`O_RDONLY|O_CLOEXEC|O_LARGEFILE`、max event bytes、queue limit 与 overflow policy。
- `name_group`：`FAN_CLASS_NOTIF|FAN_CLOEXEC|FAN_NONBLOCK|FAN_REPORT_PIDFD|FAN_REPORT_DFID_NAME_TARGET`，不得包含 permission bits 或 `FAN_REPORT_TID`；标记 V8 name/FID event profile 中与当前 output inventory 一致的 mutation/close bits。`FAN_REPORT_TID` 与 `FAN_REPORT_PIDFD` 不能同时启用；输出 I/O 的唯一 actor 是单线程 supervisor，故 PIDFD 绑定的单线程 process identity 足够，且 profile 必须证明 `pid==tid`。所有 mask bit、FID/DFID/name/PIDFD record layout、event metadata version、mount/fsid 绑定逐个有 exact UAPI row。
- `FAN_OPEN_PERM` 等 permission event 的 `metadata.fd` 是 event object FD，不是 `FAN_NOFD`。它是一个临时只读 observer FD：只允许在 responder 中执行 profile-listed `fstat/statx`（如 identity check 必需）并向 permission group 写出唯一 response；成功 response 后立即关闭 event FD并记录 close result。它不可读文件内容、写入、传递、fork/inherit 或被 supervisor 当输出 OFD 使用。event FD 由 kernel 建立时的 `FMODE_NONOTIFY` 与权限语义纳入 pinned source profile；不支持 `O_RDONLY` event-FD lifecycle 或缺失 FD 时，对应事件 deny/incomplete。参见 [fanotify(7)](https://man7.org/linux/man-pages/man7/fanotify.7.html) 与 [fanotify_init(2)](https://man7.org/linux/man-pages/man2/fanotify_init.2.html)。
- 对 supervisor 自身发起的 output open，event actor 明确为 supervisor PID/TID/start-time，而非 target；permission request 经 authenticated IPC 与唯一活动 `operation_id/io_token` 对上。Responder 在 response 前读取/哈希 raw metadata、验证 event FD identity、验证 caller actor/object/path transaction，写 exactly-one response，再 close event FD；响应 write、event-FD close 必须完成后 supervisor open 才能返回。未知 actor/event FD reuse/重复 response/响应失败均停 attempt。
- 每 group 只有一个 reader/responder，分别保留 `group_sequence` 与 drain-to-EAGAIN。不同 group 没有 global kernel order；user-space dequeue counter 仅为处理顺序。事件只通过 object+actor generation 与 token causal DAG 连接。fanotify 可合并同一 object/actor 的连续 notification；任一 event 跨 token、不可唯一归因、overflow、FAN_NOFD、短读或 unexpected merge 均 fail closed。参见 [fanotify(7)](https://man7.org/linux/man-pages/man7/fanotify.7.html)。

## 6. Final-fput observer 的机械 join

实际 kernel profile 必须为唯一真实 output OFD 定义 `file_cookie`：在真实 open 的 `fd_install`（或同等 pinned source hook）处，用 supervisor PID/TID generation、FD number generation、mount/dev/inode/object_id 与 kernel `struct file *` 生成 attempt-salted cookie；同一 pointer 再分配时 generation 递增，拒绝裸 pointer 复用。observer 在 `__fput` entry、`fsnotify_close(file)` callsite 与 `__fput` return 记录同一个 cookie、object generation、hook seq、task generation、源文件/build hash；若不能在 pinned source 对三个点证明顺序和同一 file argument，profile 不支持。

close token 的机械 join 是：`supervisor close(fd,fd_generation)` 成功 → 唯一 cookie 对应的 `__fput.entry` → 同 cookie 的 `fsnotify_close` event enqueue point → 同 cookie 的 `__fput.return` → `name_group` 中以 FID+mount/fsid/dev/inode generation 唯一匹配的 `FAN_CLOSE_WRITE` raw event → 该 group drain → kernel observer 与 fanotify lost/overflow counters 均为零 → token release。observer buffer 必须 append-only、non-overwrite，capacity 由 max open-FD 数证明；任何 reserve failure/lost counter/reader restart 即 incomplete。fanotify event-FD（若该 notification layout 提供）按 §5 限为只读 identity/close，不能当 `file_cookie` 代用品。若 profile 无法将内核 file pointer lifecycle cookie、token generation 和 kernel fanotify event 对应同一个 output object，terminal close remains missing/open；不能以时间戳近似 join。

## 7. 逐号 syscall policy artifact 仍是完成前置件

完整 `AUDIT_ARCH_X86_64` UAPI number universe、header/source commit/hash、holes、逐号 six-word ABI、handler/disposition、virtual-FD effect、path/pointer grammar、每个 allow proof 与 generator/hash 必须作为一个不可分的 versioned artifact package 入库并独立审查。profile 所有未列编号、x32、compat、`ptrace`、target `process_vm_*`、userfaultfd、bpf、perf、mount/setns/unshare、所有 `ioctl` family、io_uring 和所有 descriptor passing 默认 deny；target `seccomp` installation/USER_NOTIF 亦 deny。任何 wildcard、按 syscall 名字推断、无 exact output reachability proof 的 direct allow 均拒绝。

V15 没有伪称该 package 已存在。当前安装 header 或只读文件搜索均不是适用 kernel/source ABI profile，也不能代替真实逐号 policy/generator/predicate proof；在这组 artifacts 入库、通过 conformance tests 与 Terra High 独立 review 前 `runtime-readiness=false` 恒成立。

## 8. Scope 与权限

V15 仅增补设计，合同本身没有可执行测试或 workload 验证；同一工作轮次另对 A8 portability 与 F4 v6 synthetic candidate 执行离线测试。未读取生产文件/目录，未探测 host ptrace/fanotify/BPF/cgroup 能力，未实施任何 supervisor/kernel instrumentation，未改变 case denominator/registry/ledger/T1/T2/readiness/credit，也未启动 GenCase/native/solver/worker/GPU/queue。缺少的 runtime artifacts 与真实可信 15-case evidence 仍 open/missing。
