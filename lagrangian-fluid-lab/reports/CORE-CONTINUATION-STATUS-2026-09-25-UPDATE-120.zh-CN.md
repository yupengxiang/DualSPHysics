# Core 计划续推状态 UPDATE-120

日期：2026-09-25（Asia/Shanghai）

## 本次推进：fs-verity UAPI 原语与本机挂载能力实测

新增 `scripts/core_fsverity.py`，直接绑定并仅在实测过的 Linux x86_64 ioctl ABI 上启用 `FS_IOC_ENABLE_VERITY` / `FS_IOC_MEASURE_VERITY`；其他 OS/架构 fail closed。它提供只读/CLOEXEC/single-link regular FD 检查、bounded `/proc/self/fdinfo` mount-ID 读取、含 algorithm+digest 的稳定 measurement 编码、启用及前后 identity/measurement 复核。unsupported filesystem/kernel 映射为明确 fail-closed 异常，不存在 pathname 或普通 SHA 替代路径。调用方仍必须先完成写入和 `fsync`、关闭 writable FD，再以 O_RDONLY FD 请求 enable；内核负责拒绝仍有 writable opener 的文件。

本机只读事实：`/home` 为 ext4 `/dev/sdc1`；`/tmp` 位于 root ext4 `/dev/nvme0n1p2`；`/sys/fs/ext4/features/verity` 显示驱动支持该能力，但该信息不证明任何已挂载 superblock 已启用 verity feature。对两个挂载点各创建一份短暂 synthetic 文件并调用 enable ioctl，均得 `errno=95 EOPNOTSUPP`；测试文件/临时目录随后清理。结果与 ext4 的 superblock feature 前置条件相符，但无法由该 ioctl 单独判定具体缺失配置；superblock 仍未读取。未调用 sudo、未改变挂载或 superblock。Linux 内核文档明确 ext4 需预先带 `-O verity` 格式化或经 `tune2fs -O verity` 设置 superblock feature，且 fs-verity digest 本身不认证 producer：[官方 fs-verity 文档](https://docs.kernel.org/filesystems/fsverity.html)。

`tests/test_core_fsverity.py` **5 passed**：mount-ID/身份、measurement 固定编码、FD writable/CLOEXEC/link-count 拒绝，以及本机 enable 成功则 measure/verify、unsupported 则显式 fail-closed 的双分支测试。Core reader/compact/FD transport synthetic suite **39 passed，1 deselected**；py_compile 与 `git diff --check` 通过。所有实际 ioctl 文件均为短暂合成文件，无生产 HDF5、solver、worker、GenCase、GPU 或 queue 操作；本机没有实测成功启用 verity 的 positive filesystem 路径，无独立 GPT 6 Luna Max review。

## 剩余阻塞

本机两个可写 ext4 superblock 当前都拒绝 fs-verity enable；不能放宽 V13 的 measurement 要求，也不能改 filesystem feature 在线状态。要继续实现有效 snapshot supervisor success path，须由管理员在可维护窗口提供已启用 verity feature 的专用 filesystem，或提供另一受支持且 verity 已启用的本地挂载。除此之外，可信 producer、私有 snapshot 创建、descriptor registry/lease/revoke、broker 到 worker 的同 FD+measurement 端到端绑定、固定 launcher/runtime 身份闭合和 capability consumer 集成都未完成。当前仍不 mint capability、不开放 formal ingress；F8 `readiness_pass=false`、T1 false、资格信用为零。
