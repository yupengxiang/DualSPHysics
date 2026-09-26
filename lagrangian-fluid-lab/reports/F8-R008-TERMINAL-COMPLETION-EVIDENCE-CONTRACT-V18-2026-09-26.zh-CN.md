# F8 R008 Terminal Completion Evidence Contract v18

**状态：**additive proposal-only / diagnostic-only。V17 保持不可变历史；本版只修正其 fanotify capability 前置条件，不实现 trusted supervisor、fanotify responder、syscall policy 或 kernel observer，也不证明 runtime readiness、数值资格或执行许可。

## 1. V17 fanotify capability 条件的精确修正

V17 §3 的 permission 与 name/FID 两个 group 均在 `fanotify_init()` flags 中要求 `FAN_REPORT_PIDFD`，并要求每个当前 event 有 `actor_pidfd_ref`。V17 原先只在 permission group 的 hard-prerequisite 行标注 `CAP_SYS_ADMIN`，这不完整：Linux v6.8 上游 `include/linux/fanotify.h` 将 `FAN_REPORT_PIDFD` 列入 `FANOTIFY_ADMIN_INIT_FLAGS`（需要 `CAP_SYS_ADMIN`），而 `FANOTIFY_USER_INIT_FLAGS` 仅允许 notification class、FID bits、`FAN_CLOEXEC` 和 `FAN_NONBLOCK`。同版 `fanotify_init()` 在无 `capable(CAP_SYS_ADMIN)` 时拒绝 admin flags；`capable()` 检查 `init_user_ns`。见 [Linux v6.8 fanotify.h](https://github.com/torvalds/linux/blob/v6.8/include/linux/fanotify.h#L25-L46)、[fanotify_user.c](https://github.com/torvalds/linux/blob/v6.8/fs/notify/fanotify/fanotify_user.c#L1363-L1389) 和 [capability.c](https://github.com/torvalds/linux/blob/v6.8/kernel/capability.c#L397-L410)。

因此，除 V17 已列的 permission-event class 要求外，**permission 与 name/FID 两个精确 group profile 都必须满足 `CAP_SYS_ADMIN`**。这由 `FAN_REPORT_PIDFD` 本身决定；name/FID group 不能因使用 `FAN_CLASS_NOTIF` 而豁免。V17 的 flags、event grammar、PIDFD 身份绑定、FID/FSID/object-generation join 和 mark policy 均不变。

本版覆盖 V17 §3 中两个 group 的 capability 行，精确替换为：

| group | 额外硬前置条件 |
|---|---|
| permission | `CAP_SYS_ADMIN` 在 `init_user_ns` 中对真实 supervisor 有效；目标内核启用 permission-event 支持；精确 V17 `fanotify_init()` profile 成功；其余 V17 event-FD/action 生命周期条件全部满足 |
| name/FID | `CAP_SYS_ADMIN` 在 `init_user_ns` 中对真实 supervisor 有效（因 `FAN_REPORT_PIDFD`）；目标文件系统支持 V17 所需 FID/name；精确 V17 `fanotify_init()` profile 成功；pinned-kernel FID/FSID/object-generation 与 record-parser conformance 全通过 |

任何一个 exact profile 创建失败、`CAP_SYS_ADMIN` 在真实 supervisor 的 `init_user_ns` 有效权限集中缺失、PIDFD 记录缺失/错误、permission-event 配置不可用、FID/FSID join 不唯一、或 mark/event 队列不完整，均拒绝 attempt；不得通过删除 `FAN_REPORT_PIDFD`、改用裸 PID、切换到非特权 group 或把失败解释为环境诊断来继续。没有 `actor_pidfd_ref` 时，V17 当前事件 schema 不成立。

## 2. 本机一次性、非特权差分诊断

2026-09-26 在当前主机进行的诊断观察如下：

- 内核 `Linux 6.8.0-138-generic x86_64`；`/tmp` 是 `/dev/nvme0n1p2` 上的 ext4 mount，工作区位于独立的 `/home`、`/dev/sdc1` ext4 mount；当前进程 `CapEff=0`。
- 分别在 `/tmp` 与 `/home` 下自动清理的临时目录/文件上，以 x86-64 `syscall(303, AT_FDCWD=-100, path, handle(handle_bytes=128), &mount_id, AT_HANDLE_FID=0x200)` 调用 `name_to_handle_at`，两者均成功，返回 `handle_bytes=8`、`handle_type=1`。Linux v6.8 x86-64 syscall number 见 [syscall_64.tbl](https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/syscalls/syscall_64.tbl#L310-L314)，`AT_HANDLE_FID=AT_REMOVEDIR=0x200` 见 [fcntl UAPI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/fcntl.h#L622-L628)。这些仅是两个临时对象的一次文件句柄调用结果，不证明封闭 attempt tree 的全部目录或 pinned profile 合格。
- 以 x86-64 `syscall(300, flags, event_f_flags)` 调用 `fanotify_init`；本机 x86-64 glibc 展开的 `event_f_flags` 为 `O_RDONLY|O_CLOEXEC|O_LARGEFILE=0x80000`（该 userspace ABI 下 `O_RDONLY=0`、`O_CLOEXEC=0x80000`、`O_LARGEFILE=0`；不是跨架构通用的 numeric value）。name/FID 无 PIDFD 的诊断 flags `0x1e03` 成功，FD 立即关闭；精确 V17 name/FID flags `0x1e83`（另含 `FAN_REPORT_PIDFD`）返回 `EPERM`。这只证明无 PIDFD 的诊断 group 可创建，不满足 V17 actor identity schema。Linux v6.8 x86-64 syscall number 与 fanotify flag values 见 [syscall_64.tbl](https://github.com/torvalds/linux/blob/v6.8/arch/x86/entry/syscalls/syscall_64.tbl#L310-L314) 和 [fanotify UAPI](https://github.com/torvalds/linux/blob/v6.8/include/uapi/linux/fanotify.h#L734-L779)。
- 精确 V17 permission flags `0x0087` 返回 `EPERM`。
- `sudo -n id -u` 返回“需要密码”；本次未使用 sudo、未执行任何特权探测。

该差分与 Linux v6.8 上游 capability 分类一致；但运行主机的发行版内核源码/二进制尚未被本任务 hash-pin，以上结果不是 pinned-kernel conformance。`name_to_handle_at` 成功也不替代每个目录的实际 `fanotify_mark()`、FID event vectors、队列/mark 上限或安全 join 测试。

## 3. 运行时准入边界

目标运行 profile 必须先 pin 发行版内核 source/config/build identity 与对应 UAPI，再由拟用于正式执行的真实 supervisor 身份证明其在 `init_user_ns` 中具有 `CAP_SYS_ADMIN`，并分别以 V17 的**精确 symbolic flags 及该目标 ABI 的 raw numeric expansion**创建两个 group；需保存 user namespace identity、effective capability evidence、完整 syscall args/result/errno、PIDFD/FID parser vectors 和完整 mark inventory。不得将本节本机 x86-64 glibc 的 `event_f_flags=0x80000` 直接移植到另一 ABI；raw value 必须按 pinned userspace/kernel profile 独立固定。精确 profile 创建成功仍是必要的实测准入条件，capability 位图本身不构成通过。任一前置条件失败时，`runtime-readiness=false`，不得启动 launcher/trampoline、生产 writer 或 solver，也不得登记资格 credit。

当前本机无 sudo 非交互权限，且 V17 尚无实现或 trusted supervisor。因而本次观察仅用于修正设计条件；F8 R008 的 solver/worker/GPU/queue authority、T1 数值资格、15-case 分母和资格信用均保持不变。
