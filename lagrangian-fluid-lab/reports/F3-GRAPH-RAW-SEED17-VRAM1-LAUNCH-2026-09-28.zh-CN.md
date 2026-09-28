# F3 graph_raw seed17 VRAM1 批启动回执（2026-09-28）

通过 `core.f3.vram_batch_plan.v1` 启动 8 个尚未覆盖的 `graph_raw/seed17` diagnostic full835 rollout：`F3_DEV_01`–`F3_DEV_08`。每个作业绑定 manifest SHA-256 `8d87da6a…e680`、checkpoint SHA-256 `2da3c11c…573a`、固定 cwd/argv、独立 `/tmp/...-vram1` 输出前缀，并使用 `--maximum-steps 835 --diagnostic`。

调度策略声明每作业峰值显存 `12288 MiB`、保留 headroom `8192 MiB`、CPU slot `4`；允许已占用 GPU 共享。实际分配为 GPU4×2、GPU0×2、GPU2/GPU6/GPU1/GPU5 各 1 个。启动后 8 个进程和 8 个 progress 文件均已观察到，初始状态为 `running 0/835`；显存余量仍为约 `21985–38185 MiB`，未观察 OOM。

本批只产生 diagnostic evidence：不写 registry、ledger、denominator 或 gate，不代表 formal training/T1/T2/qualification，也不会覆盖已有 seed29 批次。terminal 后需逐例绑定 evaluation/trajectory/HDF5 validator，再另行提交报告。
