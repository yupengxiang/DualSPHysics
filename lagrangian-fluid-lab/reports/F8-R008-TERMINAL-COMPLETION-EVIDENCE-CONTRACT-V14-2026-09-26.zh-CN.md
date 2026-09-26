# F8 R008 Terminal Completion Evidence Contract v14

**状态：**仅增补设计提案，diagnostic-only；不授予 solver/执行/readiness/qualification 权限。有效合同仍为 v3–v13 与本增补；历史版本和审查记录不改写。当前没有部署可信 supervisor、tracer、broker、fanotify responder、内核 final-fput observer 或 verifier。

V13 经配置为 Terra High 的只读复核为 `REVISE`、无 P0，模型身份未获 attestation。其 P1 指出：`io_token` 仍只是事后证据而非执行门；syscall/ptrace/seccomp 的完整状态关系、final-fput 完成、跨 fanotify 队列因果与完整冻结 ABI policy 尚未定义。V14 以单一可信 syscall supervisor、目标进程虚拟输出 FD、拒绝 seccomp USER_NOTIF、per-group fanotify 序号和明确 fail-closed 状态机替换 V13 相应条款。此文档仍不是实现或执行证明。

## 1. 可执行的单写者 I/O gate

### 1.1 固定信任边界

每个 attempt 由 root-owned supervisor 在受控启动时创建。supervisor 是输出目录唯一能取得真实输出 FD 的主体；目标进程及其后代永不持有真实输出 FD、目录 FD、输出-backed mapping、fanotify FD 或可通过 `SCM_RIGHTS`/`pidfd_getfd` 取得它们的 capability。目标进程看到的输出 FD 是受 supervisor 管理的 virtual-FD slot：slot 对应一个无输出能力的 inert placeholder；全部可能消费、复制、传递、映射或改变该 slot 的系统调用必须经冻结策略处理。未知 syscall 和无法解释的 FD 操作一律拒绝并令 attempt open/missing。

唯一输出执行者是单线程 `io_supervisor` event loop。其独占持有输出 root FD、real output OFD、virtual-FD table、ptrace wait/resume 控制权和 broker operation queue。不得 fork 多个 broker worker、以共享线程并发写输出，或把真实输出 FD 传给辅助进程。另设最小权限 `fanotify_responder`，只持有 permission/name groups、只读认证 IPC 和响应所需 capability；它没有输出目录/文件 FD，不能请求或执行文件 I/O。所有输出副作用仅在 supervisor 已进入下述 token 状态机后执行。

### 1.2 Gate 状态机与 token 语义

`io_token` 是 supervisor 内部互斥状态，不是调用方提交的证据声明。每个 token 唯一对应一次被 ptrace 停住的目标 syscall 或一项 supervisor terminal/seal 操作，并绑定 `(attempt_id,task_census_epoch,tid+start_time,syscall_entry_seq,virtual_fd_generation,object_id,operation_id)`。唯一合法状态迁移为：

`STOPPED_AT_ENTRY → CENSUS_VALIDATED → TOKEN_HELD → BROKER_EFFECTS → COPYOUT_COMPLETE_OR_NONE → REQUIRED_KERNEL_EVENTS_OBSERVED → TOKEN_RELEASED`。

supervisor 代码只能从 ptrace syscall-entry stop 创建 token；token 活跃期间不得恢复第二个会触及输出或目标同一 `mm` 的 task，不得处理第二项 broker 请求。每个输出副作用都由当前 token 的 supervisor 主线程发起；broker 返回值、目标 copy-out、permission response、kernel observation 与每个 token 的因果边写入 append-only journal。事件循环崩溃、重入、序号跳号、token 未成对释放、目标 syscall 缺少 entry/exit stop、状态转换不匹配或 journal 写失败，一律保留输出、禁止 seal、标记 incomplete；不得重试该 attempt。

必须保存并验证完整 supervisor image/build/config hash、ptrace option/profile hash、syscall policy hash、virtual-FD transition journal、每次 operation 的 raw syscall entry/exit、task census epoch、broker syscall result、kernel observation refs 与 token 状态迁移。审计复核器从原始记录重建状态机；不得只信 `io_token` 自述 bool。

### 1.3 ptrace 与 seccomp 的唯一受支持关系

目标须在第一条用户态指令执行前已被 `PTRACE_SEIZE`/等价受控启动追踪；固定 `PTRACE_O_TRACESYSGOOD | PTRACE_O_TRACECLONE | PTRACE_O_TRACEFORK | PTRACE_O_TRACEVFORK | PTRACE_O_TRACEEXEC | PTRACE_O_TRACEEXIT | PTRACE_O_EXITKILL` 与冻结的 syscall-info profile。每一个 target task 的 syscall entry、exit、signal/group stop、birth、exec、exit、attach、interrupt、resume 均有单调 stop ID 和原始返回值。clone/fork/vfork 后代必须在执行用户代码前进入已记录 stop；无法及时追踪或 PID/TID 代际不明即 fail closed。

本 profile **不使用 `SECCOMP_RET_USER_NOTIF`**，不使用 `SECCOMP_USER_NOTIF_FLAG_CONTINUE`，也不混合 seccomp notification 与 ptrace syscall-stop。supervisor 在所有 target tracee 上拒绝安装/替换 seccomp filter 的 syscall 路径；若初始镜像已有 seccomp filter、出现 notification、stop sequence 与 pinned ptrace profile 不符，profile 不适用。每个 syscall 在 ptrace entry stop 时按冻结表作唯一决定：拒绝、supervisor broker emulation（跳过原 syscall并合成返回/输出 buffer），或经证明的非输出 syscall原样继续；entry 到 exit/合成返回的状态边必须完整。Linux 的 USER_NOTIF 文档明确说明该设施本身不适合作为安全策略，故本 profile 不把 notification ID 检查误当作执行 gate。

### 1.4 Descriptor 与地址空间封闭

启动器在 exec 前验证目标 FD inventory：真实输出 FDs 只存在于 supervisor；target 的 inherited FDs 是封闭 allowlist；禁止 `SCM_RIGHTS`、`pidfd_getfd`、未列入的 `fcntl`/dup/close-range、输出-backed `mmap`、`io_uring`、userfaultfd 注册及任何异步/旁路 I/O。virtual-FD 的 dup/close/inheritance 若不在 profile 的精确模型内即拒绝。即使 target 不持有真实 OFD，也需在 task census 中记录 `KCMP_VM`、`KCMP_FILES` 对照及权限错误；`kcmp` 失败、pidfd/start-time 缺失、任务出生或共享关系变化而未先停住并纳入新 epoch，均为 open/missing。

copy-out 仅由 supervisor 在 target syscall-entry stop 后执行；需先停止所有同一 `mm_id` 的任务，再复验 census、PID/TID start time、VMA 和 buffer 区间。允许区间只限 profile 明确支持、非共享、private-anonymous 的完整映射；映射带文件 backing、`MAP_SHARED`、userfaultfd registration、未知 label、跨 VMA、权限不符或不能排除未追踪 mm writer 时拒绝。supervisor 保存调用前/后目标缓冲区精确字节、返回长度、故障位置、VMA raw-row refs 及其 hash；禁止以 caller hash 代替字节。`process_vm_*`、外部 ptrace、userfaultfd 与共享可写映射均非受支持路径。不能证明进程不可被不受信任外部 writer 修改时，相关 copy-out exception 必须关闭、attempt open/missing。

## 2. 最终 close 与 kernel-side 完成

virtual-FD close 只改变 supervisor 的 virtual-FD 状态；它不被记录为真实输出 OFD 的最终关闭。真实输出 FD 的最终 close 仅由 terminal supervisor token 执行。对于要求 `FAN_CLOSE_WRITE` 的每个真实 OFD，关闭不能仅以 `close(2)` 成功、ptrace exit stop 或 fanotify drain 到 `EAGAIN` 判定完成。

冻结 kernel profile 必须含确切运行 kernel build/source identity、`__fput`/`fsnotify_close` 调用路径来源、可审计的 `__fput` entry/return observer ABI 与 loss accounting。final-close 完成需同时满足：唯一持有者关系已证明；对应 close syscall 成功；该 OFD 的 `__fput` return observer 记录已到达且与本 token/object generation 唯一关联；对应 `FAN_CLOSE_WRITE` raw event 已在正确 group 观察并关联；该 group 完成读取直至 `EAGAIN`；observer 无 lost/overflow、fanotify 无 overflow/unmatched event。由于内核可将 final `fput` 推迟至 task-work，单有 syscall exit 或即时 drain 不构成完成。无法 pin/部署/审计可靠 observer、observer event 丢失、close actor/OFD 无法唯一绑定、或 close event 语义不符时，不关闭该项、不 seal attempt。

kernel observer 只接受 exact kernel/source/profile hash 绑定；禁止把当前 host 的探测结果自动提升为其他机器的 profile。静态提案不要求执行 BPF/kprobe/fentry 能力探测，也不声称此 observer 已实现。

## 3. Fanotify 因果关系，不宣称跨队列全序

permission group 与 notification/FID-name group 保持独立 FD、独立 `group_sequence`、独立 raw-event stream 与独立 drain ID。唯一 reader/responder 由 `fanotify_responder` 担任；每个 permission event 只能对应一个仍活跃的 supervisor `io_token`，dispatcher 必须用带认证的 IPC 回复 supervisor 当前 operation ID，且只按 exact policy 作 allow/deny。它不执行 broker 工作、不持有输出 FD。dispatcher 事件循环必须能在 supervisor 的 permission syscall 阻塞期间运行；超时、重入、重复响应、没有活跃 token、actor/pidfd/start-time 不一致时拒绝并令 attempt incomplete。

不生成或声称“内核跨 group 的 global dispatch order”。每条 event 记录只含本 group sequence、读取批次/offset、raw bytes/hash、fanotify metadata、actor generation、object identity、permission response（若有）及明确的 `io_token`/operation causal edge。supervisor 的本地 dequeue 序列仅表示其用户态处理顺序，不代表两个 kernel queue 的 enqueue 全序。fanotify 事件可能 merge；只有在单一活跃 token、事件 object/actor 可唯一归属、该操作结束前无其他可产生同类 event 的 output effect 时，merge 组可绑定该 token；任意跨 token merge、丢失、unexpected event 或不能唯一归属均 incomplete。每个 group 分别 drain 到 `EAGAIN`，只形成各自队列的观察边界，不证明其他 group 的全局静默，也不替代 final-fput observer。

`FAN_OPEN_PERM` 必须由独立 responder 在 supervisor open 尚未返回时响应；IPC 中绑定 token、notification group、object/path decision、actor generation 和响应 syscall。`FAN_MODIFY`/`FAN_CLOSE_WRITE` 仅作按上述规则绑定的独立 kernel event evidence，不能用“队列读过了”推断 syscall 已执行或最终 fput 已完成。发现无 token 的 event 时 attempt 失败关闭。

## 4. 完整且可重现的 syscall policy profile

每个实际 profile 必须连同文档一起提交完整冻结材料，不能只承诺未来生成：

1. 原始 Linux x86-64 UAPI syscall-number header/table bytes、来源仓库/发行版本/commit、内核 build identity 与 SHA-256；编号 universe 包括从 0 到 profile `__NR_syscalls-1` 的每个数及明确的未分配 hole。
2. 可重现 generator、generator 源码/hash、输入 hash、生成物 hash，以及对每个 number 恰有一个的输出 row。未分配号、x32 bit、其他 `audit_arch`、compat ABI 与超出冻结 universe 的号码都有明确 deny 规则。
3. 每个 syscall row 的精确 name/null、六个 ABI word 的有符号性/宽度、指针方向、所引用 UAPI struct/layout/version/size、数组/字符串上限、FD/path/object effect、唯一 disposition、拒绝 errno 或 broker handler ID、evidence source 与 token 要求。默认动作是 deny；没有 wildcard、`unknown-safe`、按名字族推断、笼统 metadata 类别或“至少包含”清单。
4. 机械可执行且封闭的 predicate grammar，仅允许常量比较/位掩码、固定宽度 ABI decode、受界用户内存 snapshot、virtual-FD generation lookup、root-relative normalized path、object provenance 与明确枚举组合。指针 bytes 必须在所有共享 mm writer 停止时 capture；过界、坏指针、short read、未知 struct version 或无法完全判定一律 deny。
5. 每个 `allow_nonoutput_proven` row 的可审计证明，解释其精确参数域为何不可接触输出 root/virtual-FD/OFD alias、目标内存、descriptor table、mount namespace 或异步 I/O。不能给出证明的行改为 broker-emulated 或 deny。

策略显式包括、逐号处置 `ptrace`、`process_vm_readv/writev`、`userfaultfd`、`bpf`、`perf_event_open`、`mount*`/`setns`/`unshare`、所有 `ioctl` 家族、`io_uring*`、FD passing/dup/close-range、clone/fork/vfork/exec、所有 vectored/positional I/O、`sendfile`/`splice`/`copy_file_range`、mmap 家族、xattr/metadata/path mutation、sync/lock syscall 与所有 reserved/unused number。策略对 output/path/virtual-FD 操作只选择 broker emulation 或 deny；本 profile 不存在 native output-FD allowlist。syscall table 与 predicate proof 不在 V14 中伪称已经冻结：在真实、完整、hash-pinned 的 generator/table/policy artifacts 入库并接受独立复核前，F8 attempt contract 的 runtime-readiness 永远为 false。

## 5. Maps snapshot 与 census epoch

`initial_maps_snapshot` 在 tracee 及全部已知共享 `mm_id` peer 均处于同一 verified stop epoch 时读取。对同一已打开的 `/proc/<pid>/maps` FD，使用一个有总字节上限的顺序读取会话直至 EOF；记录每个 read 的返回长度/errno、总 byte count、EOF observation、PID start time、stop/census epoch 与 raw bytes SHA-256。总长超限、read error、无法证明 EOF、census epoch 改变或任何 target task 恢复均拒绝快照。单次 `read(2)` 返回短数据不作为完整快照。verifier 从这些 raw bytes 独立解析，逐原始行编号；typed `(object_id,raw_row_id)` 与 `(mapping_id,raw_row_id)` 引用必须双向闭合，所有 raw row 恰好属于一个 disjoint class，并重算 per-object 反向引用。该 stream read 语义只在所有 mapping mutator 已经被追踪且相关 mm 不可被外部 writer 改变时成立；否则 attempt open/missing。

## 6. 当前能力与权限边界

本增补仅定义后续实现/评审应验证的设计，不证明任何 Linux kernel/profile 具备所需行为。未产生 syscall profile/table artifact、supervisor、fanotify responder、final-fput observer、maps verifier 或真实 output evidence；未部署/探测 BPF/ptrace/fanotify 能力；未读取生产输出或改变 gate、registry、ledger、分母、资格/readiness/credit。未授权也未启动 GenCase、native/solver、worker、GPU 或 queue。任何缺失实现或 profile 都保持 `open/missing`，不能通过文档自签为完成。
