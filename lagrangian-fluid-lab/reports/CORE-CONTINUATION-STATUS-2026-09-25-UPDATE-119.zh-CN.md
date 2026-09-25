# Core 计划续推状态 UPDATE-119

日期：2026-09-25（Asia/Shanghai）

## 本次推进：合成 HDF5 的 descriptor-only reader 原型

为验证 V13 所需的“验 hash 与 HDF5 解析使用同一 held descriptor”是否能接入现有 reader，在 `CoreDataset` 增加显式 `snapshot_fds` diagnostic 路径。该模式要求为 manifest 中每个 case 显式提供 FD，且不得缺项或多项；仅接受只读 regular FD、unlinked/single-link inode、manifest 明确记录的正字节数，并以 `pread()` 对 held FD 的精确字节范围计算 SHA-256。HDF5 使用 `h5py.File(fileobj, ..., driver="fileobj")` 从 held FD 的 close-on-exec duplicate 读取；该模式关闭后再次访问会失败，不会退回 manifest pathname。非 FD 模式的旧 reader 路径保持兼容。

合成回归创建 tiny HDF5 后 unlink 原 pathname 并放置非 HDF5 替代物；descriptor-only reader 仍验证原内容 hash 并读取原始 state。负测拒绝可写 FD、缺失 case 覆盖及 `strict=False`。该 reader 的 `formal_eligible` 仍为 false；只验证 descriptor 绑定与常规 inode metadata 稳定性，**不**认证 snapshot producer、SCM_RIGHTS peer、supervisor registry/lease、launcher/runtime，不提供 fs-verity 或 immutability 证明，也不 mint/consume trusted capability。另一 writable FD 仍可能修改底层 inode，因此此原型不是 V13 trusted reader，不能用于 qualification/formal ingress。

定向 reader/compact tests：**37 passed，1 deselected**（跳过会导入已登记 F3 资产的慢速测试）；`tests/test_core_fd_snapshot_transport.py`：**2 passed**；`py_compile` 与 `git diff --check` 通过。一次初始 broad run 在上述 registered-F3 manifest importer 中手动中断；代码路径只检查 HDF5 文件大小，未进入 `CoreDataset` 打开或读取该 HDF5。其后所有 HDF5 内容回归均使用 `tmp_path` 合成文件。未启动 solver/worker workload、GenCase、GPU、queue 或受保护执行；无独立 Terra High 复审，不记 review PASS。

## 剩余阻塞

V13 仍缺 source-bound supervisor/trusted producer、不可变 snapshot 与 fs-verity/backend、FD registry 生命周期、broker peer/nonce 与 capability 绑定、固定 launcher/runtime identity、worker 侧端到端消费/异常撤销，以及独立安全复审。当前 ext4 superblock verity feature 未确认，因此不得启用 verity 路径或开放 formal gate。Core/F8 T1/T2 与资格信用不变，仍为零。
