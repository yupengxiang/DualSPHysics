# F3 宏观材料 T2：首批矩阵启动 readiness/authorization 阻塞审计

本次完成了实际的本机 readiness、worker、资源和入口核对，但没有启动新的 material attempt。原因是当前授权合同仍然 fail-closed：最新 v3 receipt 的 `current_launch_authorization_proven=false`，绑定 runtime spec 状态只有 `ready_for_root_queue`，而队列登记明确要求 CPU-only material job 先获得测得的 host-I/O admission。因而不能把用户任务本身误写成 root/scheduler receipt，也不能绕过 worker 直接运行。

## 核对结果

- 15 项诊断映射为 `0–11, 24, 25, 30`；v3 receipt 已记录 12 项 diagnostic-only、1 项 scientific-gate failure（row30）、1 项 engineering-evidence incomplete、1 项 matched-decimation diagnostic-only。
- row30/R003 保持 terminal failure；本次没有访问其 attempt、没有重试，也没有创建同 scope 的新目录。
- `core_material.py` 的规范化 `-m scripts.core_material --help` 入口可执行；按 job spec 的原始绝对脚本路径从仓库根目录直接调用会因缺少 `PYTHONPATH` 失败。这证明应复用 `core_runtime` frozen-worker，而不是手工绕过它。
- `core_runtime status --compact` 实际返回 `queued=0, reserved=0, launching=0, running=0, attention=0`，当前没有 material worker；六个通用 material job 是旧的 cancelled 注册，历史 pinned 结果没有被复用或覆盖。
- 资源侧可用内存约 220 GiB、无 swap、attempt 文件系统可用约 7.5 TiB、128 CPU；资源充足不是当前阻塞原因。

精确路径、SHA、入口探针、源文件 hash-only 审计和保护状态见同名 JSON receipt。此次没有用 HDF5/NPZ 库打开生产 payload，只对 coarse source 做 SHA-256 核对；没有写生产 HDF5、registry、completion、ledger、denominator 或 qualification gate。

## 最小下一步

由 root/scheduler 产生一份新的、独立的授权 receipt，绑定当前 `core_material.py` SHA、精确 source SHA、精确 argv、CPU/I/O admission 和不可复用 attempt namespace。拿到后首选 `CORE-F3-MATERIAL-COARSE-s2`，通过 `core_runtime` frozen-worker 启动，并保存完整 836 帧、checkpoint/resume、source audit、unknown/CDF/residence/coverage/performance 证据；仍固定为 diagnostic-only、T2 credit=0。row30/R003 在没有新的 frozen remedy + authorization 前不得重试。
