# Core continuation status — UPDATE-404

日期：2026-09-29

本轮继续按“先走通一个方向，再细化安全边界”的策略推进 F3 graph hidden16 与 F4 Tallwall120。新增入口、P1 加固和独立复审均保持 fail-closed；没有因为 GPU 显存充足而绕过 scheduler、来源、terminal 或正式资格门禁。

## 已提交的可交付单元

- `851f1d7a`、`d3101a12`：raw seed29/43 terminal runner 边界加固。稳定 FD、单链接、路径别名和未授权执行均 fail-closed；专属测试 `17 passed`，受影响回归 `78 passed`。
- `79ded19c`、`bd6338a6`、`732646e2`：residual seed17 receipt-bound admission、runner v2 与阻塞报告。专属测试 `10 passed`，相关回归 `332 passed`；无 terminal receipt、无真实进程/GPU。
- `fd0feff3`、`0e4972b3`：F4 external fresh-root/scheduler receipt intake 与阻塞报告。专属测试 `8 passed`；真实 fresh-root 和 scheduler-owned host-I/O receipt 仍缺失。
- `d88c1118`、`8758be98`、`692c402b`：raw seed17 runner/admission P1 收口及 synthetic scheduler authority 测试 fixture。runner 输出采用独占预留、HDF5 external/soft/VDS 拒绝、GPU UUID/PCI/child identity 绑定；admission 强制外部 Ed25519 authority、一次性 claim 和 owner/namespace/nonce/resource 绑定。测试 fixture 的 authority 只用于负/正边界测试，不代表生产信任根。
- `d33ed5b6`：对上述当前代码做独立 v3 security re-audit，专属 `20 passed`。真实剩余为 4 个 P1 和 1 个 P2：生产 scheduler trust anchor/consume witness、RolloutPlan 快照与最终 admission reread 的交叉绑定、descriptor-bound child output publication、独立 runtime GPU/terminal observation，以及 terminal receipt identity binding。

## 回归与执行边界

raw hidden16 相关测试 `264 passed`，residual hidden16 相关测试 `166 passed`，F4 Tallwall120 相关测试 `105 passed`；`py_compile`、`git diff --check` 和绝对路径 report verify 通过。所有本轮 workload/Popen/GPU 启动次数为 `0`，没有停止或重启已有进程，没有读取 production trajectory/evaluation，也没有修改 registry、ledger、denominator、gate 或 completion。

当前 GPU 快照为 GPU0/1 各约 `31,226 MiB` free，GPU2–7 各约 `48,494 MiB` free。该容量满足后续并行资源候选条件，但只有在真实 scheduler authority、fresh namespace、CPU/I-O 账本和 terminal proof 都闭合后才能启动；本轮没有裸启 batch executor。

## Core 门禁

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；9 个 registered model/seed formal runs 均缺失，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。

下一步按优先级先取得真实 scheduler-owned authority/consume witness，并完成 raw/residual 代表案例的 descriptor-bound child publication 与 terminal receipt identity binding；在独立复审通过前不启动 GPU workload，也不扩展到 96-case batch。
