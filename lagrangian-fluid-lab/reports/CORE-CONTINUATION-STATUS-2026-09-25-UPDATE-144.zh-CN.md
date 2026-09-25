# Core 计划续推状态 UPDATE-144

## rootless ext4 verity-image 路径预检

为寻找不改动现有 `/`、`/home` 挂载的 fs-verity 正向路径，只做命令/设备访问能力预检：`mkfs.ext4`、`losetup`、`unshare`、`bwrap` 和 `mount` 程序存在；`unshare --user --map-root-user true` 成功，说明可创建 rootless user namespace。可见的 loop-control 节点为 `root:disk 0660`，当前进程不属于 `disk` 组且无法读写；`/dev/loop5` 虽在目录中可见，当前进程无法打开，`losetup /dev/loop5` 返回 `ENOENT`。`losetup --find` 仅返回空闲设备名，不证明可访问或可配置该 loop device。

因此在创建任何临时磁盘镜像或尝试 mount 前即停止；没有创建镜像、打开/配置 loop device、调用 mount、改动挂载或使用 sudo。内核文档规定 ext4 必须在格式化时带 `-O verity` 或由 `tune2fs -O verity` 预先设置文件系统 feature，单纯 rootless user namespace 不会设置该 feature：[Linux 内核 fs-verity/ext4 文档](https://docs.kernel.org/filesystems/fsverity.html)。此前 `/home`、`/tmp` 上 `FS_IOC_ENABLE_VERITY` 返回 `EOPNOTSUPP` 的结论不变。

这是对“用户命名空间 + loopback ext4 镜像”路线的预检否定，不证明所有可能的独立 verity-enabled mount 都不存在；但当前进程没有可用 loop 设备，无法在本环境 rootlessly 建立所需 ext4 文件系统。PLAN 的 fs-verity 要求与正式 launch gate 保持不变。可行的下一条现成路径仍是由管理员提供已设置 verity feature、并以适当方式挂入本环境的专用文件系统；本次没有请求/执行 root 权限操作，也未启动任何 worker/solver/GPU/queue。
