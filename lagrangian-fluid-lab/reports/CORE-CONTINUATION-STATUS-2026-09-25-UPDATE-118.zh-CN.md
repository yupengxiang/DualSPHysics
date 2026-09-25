# Core 计划续推状态 UPDATE-118

日期：2026-09-25（Asia/Shanghai）

## 本次推进：rootless namespace worker 的 host-side peer binding

扩展 `tests/test_core_fd_snapshot_transport.py`：host 创建仅位于 `tmp_path` 的 Unix `SOCK_SEQPACKET` broker socket，启动一个 rootless bubblewrap worker（user namespace + PID namespace + 只读 root bind），worker 仅连接 socket、发送一字节并等待退出许可。host 读取 `SO_PEERCRED`，在 worker 存活时读取 `/proc/<peer_pid>/status` 的 `NSpid`，并对 peer PID 调用 `pidfd_open()`。

当前主机探测结果：peer credentials 的 PID 是 namespace worker 对应的宿主 PID，不是外层 bubblewrap supervisor PID；host `/proc` 可见其 NSpid 映射；`pidfd_open(peer_pid)` 成功，返回的 pidfd 带 `FD_CLOEXEC`。rootless worker 的 peer UID/GID 映射为宿主当前 UID/GID。该 API 可以将一次 socket session 关联到一个活跃进程实例，但同 UID 是共享的，PID/pidfd 本身也不证明 executable、loaded Python modules、代码来源或 runtime identity。

`tests/test_core_fd_snapshot_transport.py` **2 passed**，包含前一项 `SCM_RIGHTS`/pathname replacement 测试；测试在无 bwrap/user namespace/pidfd 能力的环境显式 skip，且始终只使用临时文件/socket 和空操作级 namespace worker。没有读取生产 HDF5/BI4，没有运行 solver、GenCase、训练、worker workload、GPU 或队列。

## 信任边界与后续

host-side `SO_PEERCRED + pidfd` 是进程实例绑定原语，不是可信 launcher 证明，也无法区分同 UID 的不受信任进程。V13 仍须定义并实现 out-of-band 固定 launcher/runtime identity、启动器与 supervisor 的父子关系、socket session/attempt/nonce 绑定、descriptor registry 的 lease/consume/revoke/close 状态机及异常清理。当前 ext4 superblock 的 fs-verity feature 仍未知，`sudo -n tune2fs -l /dev/sdc1` 因需密码未执行提权；snapshot backend 继续 fail-closed。未 mint capability，不改变 T1/T2/资格信用或 formal-job 状态。
