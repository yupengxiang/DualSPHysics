# Core continuation status — UPDATE-402

日期：2026-09-29

本轮对 F3 graph terminal 边界做了一次独立安全审计，并按 raw/residual/common 写集并行修复。审计发现 4 个 P1、1 个 P2；active execution paths 已完成对应 hardening，但未授权的 production capability 仍保持关闭，不能把审计合同或本地结构一致性当作真实运行证明。

## 安全审计与修复

- `95d79a26`：隔离安全审计合同，固定发现 TOCTOU/path reopen、HDF5 external/soft/VDS link、process proof 自声明/缺 plan identity、residual token/injectable Popen、unknown-field 不一致等问题。
- `8af0b68d`：公共 HDF5 validator 加入 external/soft/VDS、symlink/hardlink 拒绝，以及 fd/stat/size/双 SHA 稳定性检查；合成对抗测试 `18 passed`。
- `9e4d09a7`：raw process proof 改为 sealed real Popen/wait record，并绑定完整 plan/manifest/training/checkpoint/command/artifact descriptor；raw 相关回归 `75 passed`。
- `dae6b8ee`：residual 移除 capability-token/injectable-Popen 绕过，强化 process/artifact/HDF5 path identity；residual 定向回归 `43 passed`。
- `f69206f1`：同步审计测试到 residual 修复后的边界，避免旧断言把已移除的 token 当作必需行为。

## Admission 现状

`1d726119` 的 production-validator admission contract 已完成 source binding，但 admission 仍为 `false`：缺独立真实 Popen/wait proof、真实 production HDF5 artifact receipt 和一次性 namespace 外部保留证明。`8900e148` 的 production validator capability 也仍未授予；`6eac3b1e` 生成的 6 个 fresh diagnostic envelope 仍为 readiness/launch/credit=`false/false/0`，natural-exit proof=`0/6`。

这意味着安全修复已阻断已知绕过，但尚未获得真实 execution authority。未授权 capability 内部的自声明 proof 不会被任何 bridge 接受，也不能用来打开 GPU workload。

## 验证与门禁

相关跨模块回归最终为 `388 passed`；`py_compile`、report CLI verify、`git diff --check` 通过。全程未启动 workload/Popen/GPU，未读取生产数据，未停止/重启已有任务，未修改 registry、ledger、denominator、gate 或 completion。

Core 仍为 `can_finalize=false`：T1 families=`F3/F4`（2/3），macro T2=`0/2`，formal training=`0/9`；missing training runs 为 9 个，T1 case-run 缺 `288`（目标 `432`），material case-run 缺 `288`（目标 `288`），independent reproduction=false，credit=`0`。

下一步必须获得可信的一次性 namespace/producer reservation，并把真实自然退出、真实 artifact descriptor 和独立 HDF5 validator receipt 接入 bridge；在这些证据到位前继续 fail-closed，不进行裸执行。
