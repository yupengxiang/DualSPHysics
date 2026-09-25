# Core 计划续推状态 UPDATE-143

## Core completion 复核与 rootless snapshot 原语探测

### 只读 completion 账本

`./.venv/bin/python scripts/core_campaign.py status` 返回 `can_finalize=false`、`issues=[]`、`evidence_valid=true`、`causal_lineage_contracts=true`。正式 T1 家族仍是 F3/F4 两个，宏观 T2 家族为 0，正式训练为 0/9；目标 T1 分母 432 个 case-run 全缺，其中 288 个已登记、144 个尚未登记，材料分母 288 个全缺。独立全产品异机复现仍未通过。命令未使用 `--write-snapshot`，没有改写 completion 快照。

### 仅内存 synthetic 的 memfd sealing 探测

在 Linux 6.8 rootless 进程中创建 anonymous memfd，使用 h5py 写入一个含 8 个整数的临时 HDF5，再施加 `F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL`。`F_GET_SEALS` 返回完整 `0xf`；后续 `pwrite` 被 `EPERM` 拒绝；dup FD 的 `fstat` 身份一致；SHA-256 流式读取成功；h5py 又从 dup FD/file object 读回 `[0,1,2,3,4,5,6,7]`。所有内容只存在匿名 memfd，未创建临时路径、未访问生产数据，也未启动 worker。

同一只读环境盘点可见 `/` 与 `/home` 为 ext4；`/dev/tpm0`、`/dev/tpmrm0` 不存在。security LSM 列表为 `lockdown,capability,landlock,yama,apparmor`；IMA policy 节点存在但 root-owned 且不可读，因此本次不能确认其 appraisal 配置。此前 `/home` 与 `/tmp` 上 `FS_IOC_ENABLE_VERITY` 的 `EOPNOTSUPP` 结果仍有效，本次没有提权、重配或更改挂载。

### 结论及边界

memfd seal 是当前主机可用的 rootless、同一文件对象不可写原语，说明“snapshot immutability”这一层不必然需要 sudo。但它不提供 fs-verity measurement，也不认证创建者、输入来源、supervisor 或 signer；任何同 UID 进程都能创建自己的 sealed memfd。Linux 文档也明确 fs-verity 的 digest 仍须由受信代码依据可信签名根认证。参见 [Linux `memfd_create(2)` 文档](https://man7.org/linux/man-pages/man2/memfd_create.2.html) 与 [内核 fs-verity 文档](https://docs.kernel.org/filesystems/fsverity.html)。

因此这只是一个可能供后续重新审查的 rootless snapshot 备选技术输入，不等同于当前 V13 的 fs-verity hard gate，不能作为隐式降级、trusted root/capability、正式 reader/worker 后端或资格证据。若未来决定评估替代方案，仍需单独冻结 trust/signature、descriptor registry/FD transfer、同 FD HDF5 reader、RAM/临时存储上限及崩溃恢复合同并通过静态复核。当前 gate、授权、T1/T2 状态均不变。
