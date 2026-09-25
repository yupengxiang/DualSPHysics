# Core 计划续推状态 UPDATE-117

日期：2026-09-25（Asia/Shanghai）

## 本次推进：验证 V13 descriptor transport 的内核原语

新增 `tests/test_core_fd_snapshot_transport.py`，只使用 `tmp_path` 合成 regular file 与 Unix `SOCK_SEQPACKET` socketpair。测试通过 `SCM_RIGHTS` 传递只读 FD，并验证：

- 接收端与发送端观察到相同的 `(st_dev, st_ino)`；通过共享 seek offset 验证是同一 open-file-description，而非 pathname reopen。
- 接收 FD 保持 `O_RDONLY`，并在 `recvmsg(MSG_CMSG_CLOEXEC)` 后带有 `FD_CLOEXEC`。
- 原路径被移动并创建 replacement 后，接收 FD 仍绑定原 inode、link count 为 1，并读取到原始合成字节。

定向测试 **1 passed**，测试文件 `py_compile` 与 `git diff --check` 通过。此证据可支撑 V13 中 broker→worker FD 传递的低层合同，但 socketpair 的双方仍在同一测试进程中；它不认证 peer、启动器、supervisor、descriptor registry 或 worker runtime。

## fs-verity 查询与边界

在用户授权的探索范围内，对已确认的挂载源 `/dev/sdc1` 尝试非交互只读命令 `sudo -n tune2fs -l /dev/sdc1`。命令因 sudo 需要密码而退出，没有发生提权或任何文件系统写操作。因此 ext4 superblock 的 `verity` feature 仍未确认；不据此启用或声称 fs-verity 可用。

没有读取生产 HDF5/BI4，没有创建持久 snapshot，没有启用 fs-verity，也没有运行 worker、solver、GenCase、GPU 或队列。V13 trusted peer/supervisor/registry、same-FD HDF5 consumer 与 runtime identity 仍未闭合；formal jobs 为零，资格信用与 T1/T2 状态不变。
