# F3 显存共享批调度器（2026-09-28）

本提交新增 `core.f3.vram_batch_plan.v1`。它把 GPU 视为可共享资源：设备已有进程不再自动排除，只有在“观测到的 free VRAM − 已规划的作业峰值显存”仍高于保留 headroom 时才准许规划。当前默认保留 `8192 MiB`，并按作业独立 output namespace 拒绝覆盖。

实现只负责 source-bound diagnostic launch planning：

- 读取固定格式的 `nvidia-smi` 显存快照，也支持注入合成快照；
- 绑定 manifest/checkpoint SHA、case/model/seed、argv、cwd 和输出路径；
- 同一 model×seed×case、输出路径或 job id 重复时 fail-closed；
- 强制 `--maximum-steps 835 --diagnostic`，默认 dry-run；显式执行还需要额外 opt-in；
- 永远输出 `diagnostic_only=true`、`formal=false`、`formal_eligible=false`、credit=`0`，不触碰 registry、ledger、denominator 或 gate。

真实机器快照记录了 8 张 RTX 6000 Ada 的当前显存余量约 `21.5–38.5 GiB`；本次只将该快照作为合同回执，合成 3-job fixture 规划通过，实际启动数为 `0`。专项测试 `10 passed`，`py_compile` 与 `git diff --check` 通过。

该模块不会替代 root/scheduler authorization，也不会把 diagnostic rollout 升格为 formal/T1/T2。后续可用它安全生成未覆盖的 model×seed×case 批次，再由独立 receipt aggregator 处理 terminal 产物。
