# Core 计划续推状态 UPDATE-121

日期：2026-09-25（Asia/Shanghai）

## 本次推进：将 fs-verity measurement 接入同 FD HDF5 reader

扩展 `CoreDataset` 的 descriptor-only diagnostic API，新增 exact all-case `snapshot_measurements` map。提供 measurement 时，必须持有只读、CLOEXEC、single-link regular FD（`st_nlink==1`）；在构造时验证 kernel measurement 并固定 `(device,inode,mount_id,size,nlink,mtime_ns,ctime_ns)` identity。raw HDF5 SHA-256 仍以 held FD 的 `pread()` 计算，并在哈希前后复验 verity measurement/identity；HDF5 由同一 open-file-description 的 `F_DUPFD_CLOEXEC` duplicate 经 `h5py` file-object driver 打开。初始 HDF5 轴检查及 `times()`、`read_state()` 完成后再次核验。无 measurement、identity、字节数或 reader 状态匹配时拒绝；不存在 pathname reopen。所有 `CoreDataset` 实例仍 `formal_eligible=false`，measurement 参数本身不是 trusted capability。

新增两种区分明确的合成测试：一项在本机 ext4 对未启用文件验证失败，确认不回退到已替换的 manifest pathname；另一项 stub 内核 verifier，仅验证身份/measurement 检查的调用顺序以及 HDF5 仍从 held FD 读取。stubbed case **不**证明 fs-verity 已启用或不可变。定向 contract/compact/FD-transport/fsverity suite **46 passed，1 deselected**；Core learning suite **47 passed**；py_compile 与 `git diff --check` 通过。测试只使用 `tmp_path` 合成 HDF5；未读生产 HDF5，未运行 solver/worker/GenCase/GPU/queue。

## 仍未闭合

当前 `/home` 与 `/tmp` ext4 enable ioctl 实测均为 `EOPNOTSUPP`，因此真正的内核 fs-verity 正向路径及 reader+kernel 联合验收尚不可进行。调用方 measurement 未由 supervisor capability 认证；可信 producer、snapshot copy/fsync/enable、descriptor registry 生命周期、broker/peer/nonce 到 worker 的身份与 FD 绑定、固定 launcher/runtime 闭合、正式 consumer 集成及 GPT 6 Luna Max 独立审查仍缺。F8 R008 readiness/T1 与 Core T1/T2 仍 false/zero credit；未启动受保护任务。
