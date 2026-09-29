# Core runtime scheduler identity audit — 2026-09-29

范围仅限 `scripts/core_runtime.py` 及其两个专项测试文件。审计发现三处真实 fail-open 边界：`prepare-launch` 没有一次性 reservation consume 和精确 attempt 路径绑定；terminal receipt 只检查 schema/job/attempt，未绑定 scheduler 的 host/GPU allocation 与 launch/heartbeat 链；metadata 读取会跟随 symlink，也没有稳定 inode 检查。

已实施最小 fail-closed 修复：

- reservation binding 固定 job、attempt、精确路径、queue spec hash、reservation id、host hostname/boot id、GPU UUID/index；`O_EXCL` owner-only marker + fsync 实现一次性 consume，跨 attempt/token 重放拒绝。
- `probe`、`prepare-launch`、worker、heartbeat、collect、terminal finalization 复用同一 identity chain；worker 在 launch 前及 GPU 采样期间复核 host boot identity 与 GPU UUID/index。
- JSON metadata 使用 `O_NOFOLLOW`、single-link regular-file 检查及读前后 inode/stat 对比；worker lock 与 required output 同样拒绝 symlink/hardlink。

验证：scheduler 专项 `17 passed`，Core runtime 回归 `28 passed`；`py_compile` 和 `git diff --check` 通过。未启动 production workload/solver/GPU job，未停止或重启既有 runtime/archive 进程，未创建或消费伪造 production evidence。

残余边界：该修复提供 fail-closed 的 reservation、路径、host/GPU 与 receipt 链绑定，但不声称能抵御同 UID 恶意进程同时改写受信 runtime 或 scheduler state；独立生产 scheduler/launcher attestation 仍属于 `core_runtime.py` 之外的信任根。
