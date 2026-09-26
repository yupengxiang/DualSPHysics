# UPDATE-214：F8 fanotify PIDFD capability 前置条件修正

时间：2026-09-26（Asia/Shanghai）

## F8 R008 terminal evidence contract

对 V17 的非特权差分预检发现：在本机 `Linux 6.8.0-138-generic x86_64` 上，`/tmp`（`/dev/nvme0n1p2`）与工作区所在 `/home`（`/dev/sdc1`）是两个不同的 ext4 mount，当前进程 `CapEff=0`。在两处分别创建并自动清理临时文件，以 `syscall(303, AT_FDCWD=-100, path, handle_bytes=128, &mount_id, AT_HANDLE_FID=0x200)` 调用 `name_to_handle_at`，均成功，返回 8-byte handle、`handle_type=1`。以 `syscall(300, flags, event_f_flags)` 调用 `fanotify_init`，其中 `event_f_flags=O_RDONLY|O_CLOEXEC|O_LARGEFILE=0x80000`：name/FID 无 PIDFD flags `0x1e03` 成功，加入 PIDFD 后的 exact V17 flags `0x1e83` 返回 `EPERM`；exact V17 permission flags `0x0087` 亦返回 `EPERM`。所有成功创建的 fanotify FD 均立即关闭；未创建 mark、读写生产输出或 HDF5/PART/BI4。

Linux v6.8 上游 `include/linux/fanotify.h` 将 `FAN_REPORT_PIDFD` 列入 `FANOTIFY_ADMIN_INIT_FLAGS`；`fanotify_init()` 的无特权分支拒绝 admin flags，而 `capable(CAP_SYS_ADMIN)` 指向 `init_user_ns`，故 V17 两组 exact profiles 都要求初始 user namespace 中的 `CAP_SYS_ADMIN`，不只是 permission group。新增 [V18 合同](F8-R008-TERMINAL-COMPLETION-EVIDENCE-CONTRACT-V18-2026-09-26.zh-CN.md) 作为 additive overlay：只修正 capability 前置条件，保留 PIDFD actor identity join，不允许降级 PIDFD。

本次 `sudo -n id -u` 返回需要密码；未调用 sudo。当前发行版内核源码/二进制尚未 hash-pin，本机诊断不是 pinned-kernel conformance；FID 成功不证明完整目录 inventory、mark/event vectors 或 runtime readiness。V18 为 proposal-only；无 trusted supervisor、两个实际 group 的特权 conformance、fanotify responder、final-fput observer 或完整 syscall policy。未运行 launcher、solver、worker、GPU/queue；未改 scope、registry、ledger、分母、T1/T2 或资格 credit。总体 Core 状态未因本次文档调查改变。

## 验证

仅作主机非特权 syscall 差分诊断及 Linux v6.8 上游源码核对；文档合同变更未运行 pytest 或工作负载。GPT-6 Luna Max 配置 subagent 首轮独立只读复核认为核心修正正确、无 P0/P1；其 P3 capability namespace 和 exact-argv 记录建议已补入 V18。其 P2 “V18 自称未进行本次探测”与当前 V18 文本不符，疑似混淆 V17 历史记录；已请求针对修订稿作窄范围 follow-up。reviewer 身份未独立 attested，不记作正式模型身份签核。
