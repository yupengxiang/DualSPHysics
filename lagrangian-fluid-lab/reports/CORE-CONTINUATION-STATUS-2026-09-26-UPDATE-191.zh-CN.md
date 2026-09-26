# UPDATE-191：F3 model-material v2 synthetic profiler

时间：2026-09-26（Asia/Shanghai）

新增 `f3_native_volume_mls_model_material_v2_profile.py`，沿用 v1 profiler 的外围计时方式，但针对 v2 streaming trace 增加 provider 初始化/field 调用、MLS reconstruction、RK4、HDF5 append/hash-chain、recovery、summary 和 SHA-256 阶段计时。默认配置为 512 seeds × 4096 synthetic particles × 20 intervals；临时 HDF5 和 trace 自动清理。入口不接收 source 路径，因此不能误读生产数据；qualification 固定为 `none`。固定合成规模上限，并在开始任何合成文件生成前要求 1 分钟 host load 不超过 process-visible CPU 数；无法读取 load 时也 fail closed。

专项测试 **4 passed**：load gate 边界/拒绝、模型与 reference 两类 provider 的小型 synthetic profiling、计时调用数闭合，以及 CLI 在资源拒绝时报告 `profile_started=false`。`py_compile`/`git diff --check` 通过。另对默认命令作实际门控探针，因 1 分钟 load `172.387 > 128 CPUs` 返回 `deferred_resource_gate`，确认大型 profile 在创建临时 HDF5 前未启动。

因此本更新交付了可复现的 v2 profile harness，不是阶段性能结果；512×4096×20 的实际 synthetic profile 仍待资源门通过后运行。当前不根据 v1 或微型 fixture 推算 v2 生产 CPU 上界，不作 root resource decision，也未触及生产 HDF5、worker、solver、GPU、queue、registry 或 ledger。整体 Core/T1/T2 目标仍未完成。
