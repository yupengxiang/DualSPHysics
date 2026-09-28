# F4 Tallwall120 material readiness projection v1

本报告只消费七份 bounded JSON receipt；不打开或读取 HDF5，也不授予任何运行权、正式资格或 credit。

- 状态：`blocked_fail_closed`
- `diagnostic_only=true`，`launch_admitted=false`，`formal=false`，`T1=false`，`T2=false`，`qualification=false`。
- `credit=0`、`qualification_credit=0`；registry、ledger、denominator、gate、completion、PLAN 和 queue mutation 全部为 `0`。

## 绑定范围

- scope：`F4_resting_pool_laminar_tallwall120_x_v1`；case：`F4_resting_pool_laminar_tallwall120_x_v1_DEV_07`。
- source：`campaigns/core-v1/cfd/f4-tallwall120-production-archives-v2/f4-tallwall120-production-dev-07/product/trajectory.h5`；SHA-256：`6ae8ca7062e1fa15779fc9ad491d1117455700315c6a1ef4a12326458f0976ae`。
- q：`0.23437500000000008`；dp：`0.0075`；native window：`4.340002980805959 s`；required event window：`8.68 s`。

## 当前阻塞

- root/scheduler authorization：未闭合；`launch_admitted=false`。
- terminal evidence：`missing`；event window 为 `right_censored_or_unresolved`。
- material sidecar：`0/32`，缺失 `32` 个。
- collection source path 仍为 archives-v1，而 proposal target 为 archives-v2；reader manifest SHA 仍未精确绑定。

## 安全边界

输入路径限制在 checked-in lab root；report/markdown 输出固定在 `reports/` 子目录。读取通过持有的 directory FD 逐组件拒绝 symlink，并执行 open 前、读后 inode 以及双读 hash/字节复核；输出拒绝 symlink、hardlink 和替换。duplicate key、非 finite 数值、越界大小、路径 traversal、错误 record-id、错误 schema、malformed 结构和超深 JSON 均 fail-closed。报告验证会重新从七份输入构建并逐字节绑定 SHA。

该 projection 是 readiness 记录，不是实际 material trace、terminal evidence、T2 acceptance 或 launch authorization。
