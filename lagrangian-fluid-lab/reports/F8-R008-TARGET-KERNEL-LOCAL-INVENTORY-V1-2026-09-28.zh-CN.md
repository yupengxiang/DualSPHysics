# F8/R008 本机 target-kernel bounded inventory V1

- 状态：`diagnostic_only_local_target_kernel_inventory_incomplete`
- uname release：`6.8.0-138-generic`
- kernel release evidence：`present`；config：`present`；UAPI 样本：`present`；headers：`present`
- build-id：`not_observed_in_allowed_scope`；source commit：`not_observed_in_bounded_header_scope`；source tree：`not_proven`

## 只读边界

仅读取 uname、匹配的 `/boot/config-<release>`、`/lib/modules/<release>/build` 链接元数据，以及 `/usr/src` 下有限的header/UAPI 元数据与固定样本哈希；未读取 kernel image、生产 BI4/HDF5，未执行 privileged probe、挂载、系统写入、native/solver/worker/GPU/queue。

## 配置样本

- `/boot/config` 与 header `.config` SHA-256 相等：`True`
- UAPI 样本 inventory SHA-256：`ee6168f6f4d8b9d745fe6440cfb01bd13cc87472ef7b279a1140682be1090ed3`
- header bounded metadata SHA-256：`4602a1c7e058c793f5fd21f047f658e05edc5e076252f84bf2ea853b76f2d5f2`
- complete UAPI/header/source tree hash：`未生成（bounded sample only）`

- `CONFIG_FANOTIFY` = `y`
- `CONFIG_FANOTIFY_ACCESS_PERMISSIONS` = `y`
- `CONFIG_SECCOMP` = `y`
- `CONFIG_SECCOMP_FILTER` = `y`
- `CONFIG_X86_X32_ABI` = `n`

## Fail-closed 结论

- pins：`{"build_id_pinned": false, "config_pinned": true, "header_pinned": false, "kernel_release_pinned": true, "source_commit_pinned": false, "source_tree_pinned": false, "uapi_pinned": false}`
- readiness / T1 / formal admission：`false`
- qualification credit：`0`
- source commit/tree 与 build-id 未被证明，不能把本机 header package 升格为 target pin。

## Blockers

- source tree and source commit are not observed in the bounded header scope
- kernel build-id is not observed in the allowed bounded paths
