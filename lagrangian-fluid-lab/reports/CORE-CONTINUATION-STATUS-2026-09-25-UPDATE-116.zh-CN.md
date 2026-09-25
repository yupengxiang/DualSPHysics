# Core 计划续推状态 UPDATE-116

日期：2026-09-25（Asia/Shanghai）

## 本次推进：V13 snapshot/fs-verity 主机能力只读盘点

- 当前运行内核：Linux `6.8.0-138-generic`；`/boot/config-6.8.0-138-generic` 显示 `CONFIG_FS_VERITY=y`。
- workspace 位于 `/home` 的 ext4 rw mount；对应 source 显示 `/dev/sdc1`。本地没有 `fsverity` 用户态 CLI。
- rootless bubblewrap `0.6.1` 的只读隔离 smoke probe 成功：user namespace、PID namespace 与全根只读 bind 内运行 `/bin/true`。这只说明本环境允许该基本隔离组合，不证明它满足 V13 supervisor/broker 威胁模型。
- 无提权读取 `/dev/sdc1` 的 ext4 superblock 被拒，因此当前不能确认该 filesystem instance 是否启用了 ext4 `verity` superblock feature；kernel config 为 `y` 不能替代此项检查。依当前 V13 fail-closed 条款，未确认时不实现或声称 verity-backed snapshot 可用。

Linux kernel [fs-verity 文档](https://docs.kernel.org/filesystems/fsverity.html)说明：`FS_IOC_ENABLE_VERITY` 检查 inode 的 write access，但调用必须使用 `O_RDONLY` FD，且执行期间不能有任何 writable FD；ext4 filesystem 还须具备 verity feature。fs-verity 为文件读取提供 integrity，不会自行认证摘要的来源，因此仍要有受信任的 digest/signature 根。由此，单文件 enable 操作不等同于“必需 sudo”；文件权限、filesystem/kernel 支持与可信 supervisor 是不同条件。rootless namespace smoke test 也不能替代 producer、root、runtime、descriptor registry 或 same-FD worker 的 V13 验证。

## 安全边界与后续

本轮仅读取 kernel config、mount/user namespace 元数据并运行隔离内的 `/bin/true`。没有使用 sudo、没有打开或读取生产 HDF5/BI4、没有创建 snapshot、没有启用 fs-verity，也没有更改 filesystem、mount 或 sysctl。没有资格、T1/T2 或 formal-job 状态变化。

下一项安全工作是继续静态闭合 rootless supervisor 的身份、snapshot 生命周期、descriptor registry 与 worker 接 FD 合同；对真实 ext4 verity feature 的确认仍保持未决，不能以本轮内核配置推断通过。
