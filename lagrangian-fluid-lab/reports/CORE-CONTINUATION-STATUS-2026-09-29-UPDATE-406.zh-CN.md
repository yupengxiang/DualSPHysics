# Core continuation status — UPDATE-406

日期：2026-09-29

本轮继续按“先走通一个方向，再细化安全边界”并行推进 graph hidden16、F4 receipt、F8 target pin 和 A8 reproduction。raw seed29/43、residual seed17、F4、F8、A8 的安全入口均完成独立审计/加固并分别提交；MLP 方向还修复了一个 hardlink 负测的错误诊断优先级。所有结果仍严格 fail-closed、zero-credit，没有用静态合同冒充真实外部执行证据。

## 已提交的可交付单元

- `6ca0727e`：residual seed17 admission/runner v2 安全审计。一次性 receipt、Ed25519 authority、稳定 FD/path、descriptor-bound output 和 terminal identity 均保持 fail-closed；专项 `10 passed`，residual 联合回归 `187 passed`。真实 scheduler、GPU/child、sealed Popen/wait 和独立 HDF5 证据仍缺失。
- `6d3420bd`：raw seed29 admission snapshot/digest、manifest/training/checkpoint/namespace/nonce/command 跨绑定和 final stable reread 加固；专项 `34 passed`。
- `fa82f8ac`：raw seed43 对称 admission/receipt/runner 复核和最终 descriptor 重读加固；专项 `35 passed`。raw 17/29/43 相关回归 `101 passed`，当前 raw hidden16 显式测试集 `339 passed`。
- `e1ee1a18`：A8 reproduction/root-attestation validator 拒绝 metadata 伪造，加强 checkpoint provenance/model lineage；专项 `35 passed`，相关回归 `98 passed`。另一物理机、distinct data root、trusted-root review 和 host attestation 仍不存在。
- `5ea37387`：F8 R008 trusted target-kernel pin/intake 加固，防止 target/source/config/build/runtime pin 不完整时升格 readiness；专项 `68 passed`，相关回归 `87 passed`，当前 pin/readiness 显式过滤集 `34 passed`。
- `f3b5be02`：F4 Tallwall120 receipt intake 加固 raw/canonical bytes、root identity、TOCTOU、fresh namespace、replay guard 和状态派生；专项 `32 passed`，相关 F4 回归 `164 passed`，当前 Tallwall120 过滤集 `236 passed`。真实 fresh-root/scheduler-owned host-I/O receipt 仍缺失。
- `8bfd5152`：修复 MLP artifact sidecar hardlink 负测的错误诊断优先级：在 matrix reread 前先检查 caller-bound checkpoint inode，保持原有 fail-closed 语义；修复后 MLP hidden16 全套 `158 passed`。

## 回归与执行边界

当前 HEAD 的显式测试集为 raw `339 passed`、residual `187 passed`、MLP `158 passed`、F4 `236 passed`、F8 `34 passed`、A8 `35 passed`；新增代码通过 `py_compile`、JSON 报告校验和 `git diff --check`。本轮没有启动 production workload/Popen/GPU，没有读取 production trajectory/evaluation，没有停止或重启已有进程，也没有修改 registry、ledger、denominator、gate 或 completion。

曾尝试从仓库根目录执行全量 `pytest -q`，但该命令递归收集 ignored runtime snapshot/link trees，经过 `2374.56 s` 后在 collection 阶段出现 `11798` 个 `ENAMETOOLONG` 错误并中断；这不是代码测试通过/失败结论，不计入回归。后续只从显式 `lagrangian-fluid-lab/tests` 路径运行专项，避免把归档快照当成测试树。

当前 GPU 快照为 GPU0–7 各约 `48,497 MiB` free。允许在已有任务共存且独立 admission 确认显存/CPU/I-O 足够时使用 GPU，但显存充足不替代 scheduler trust anchor、runtime identity、terminal receipt 或 formal gate。

## Core 门禁

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；9 个 registered model/seed formal runs 均缺失，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。当前可继续推进的是静态边界与 receipt intake；生产 scheduler authority、真实 GPU/child identity、F4 fresh-root receipt、F8 target runtime pin、A8 外部主机复现和 formal terminal evidence 仍需要外部状态/可信执行环境。
