# A8 单案例 Ada↔H200 异机配对复现审计（2026-09-24）

## 结论

找到并配对了 2026-09-20 在 Ada 与 H200 上完成的两次既有 F3 全时域诊断 rollout。使用两份运行报告绑定的同一版 Core 比较代码，对完整 trajectory、固定分母评分和物理统计进行配对检查，结果为 `passed=true`，没有 mismatch。该结果只证明一个诊断案例在两台主机上的数值可复现；不构成科学资格、正式训练、完整产品复现或 Core 完成。

机器收据：[a8-cross-host-diagnostic-pair-v1.json](../campaigns/core-v1/reproduction/a8-cross-host-diagnostic-pair-v1.json)，SHA-256：`c94742d50ac93871a5e37eeeb60c0e82d892f87549036191f1f4cbeadb06bf9b`。

## 对照范围与结果

两边使用相同的 `F3_registered32_core_native_v2` 包、F3 validation 案例 `F3_DEV_08_a0p953125`、34560 个粒子、835 个 transition（836 个状态帧），以及 SHA-256 为 `670880ac…a1cfb7` 的 MLP seed17 / hidden64 / update16 检查点。两边都完成 835/835 rollout transition，`finite_rollout_complete=true`，未使用未来状态输入。登记数据清单 SHA-256 为 `8d87da6a…76e680`，包 SHA-256 为 `00c8d22f…3a2a`。

| 指标 | Ada（hostname `user-SYS-421GE-TNRT`） | H200 | H200 相对 Ada |
|---|---:|---:|---:|
| Selection score | 0.05771994590593965 | 0.05771994589563422 | 绝对差 `1.03e-11`（相对 `-1.79e-8%`） |
| Position RMSE frame mean | 0.0515941251058512 m | 0.051594125099817735 m | 差 `-6.03e-12 m`（相对 `-1.17e-8%`） |
| Velocity RMSE frame mean | 0.17267509276560664 m/s | 0.1726750927242839 m/s | 差 `-4.13e-11 m/s`（相对 `-2.39e-8%`） |
| 跨机逐帧最大位置绝对差 | — | — | `5.96e-8 m`（门限 `1e-5 m`） |
| 跨机逐帧最大速度绝对差 | — | — | `2.98e-8 m/s`（门限 `1e-4 m/s`） |

固定分母评分比较通过，score absolute tolerance 为 `1e-4`；time、particle identity、mass 和 valid mask 精确一致，physics 计数及 failure category 精确一致，physics 浮点门为 `rtol=1e-4, atol=1e-6`。两个报告都为完整 835-frame 预测，无首个失败帧，raw error coverage 均为 1.0。

## 资源记录

| 主机 | 执行 wall time | GPU process reservation | 子进程 CPU time | 采样 GPU 峰值 | 采样进程树 RSS 峰值 |
|---|---:|---:|---:|---:|---:|
| Ada | 2445.56 s | 0.67932 h | 1926.90 s | 622 MiB | 1027.72 MiB |
| H200 | 1998.59 s | 0.55516 h | 2061.15 s | 738 MiB | 1050.39 MiB |

H200 本次 wall time 和记录的 GPU process reservation 均比 Ada 低约 18.28%；子进程 CPU time 高约 6.97%。这只是单案例、单 seed 的两次观测，不作硬件总体性能推断。execution receipt 没有记录 device-occupancy union time，不能把 process reservation hours 当作设备占用时间。

## 谱系、状态与限制

- Ada attempt [`result.json`](../campaigns/core-v1/runtime/attempts/ada-a8-f3-mlp-seed17-v3-fullcase-reproduce-v1/20260920T055509-90f7455a5a24/result.json)（`20260920T055509-90f7455a5a24`）：execution `succeeded`、return code 0、无缺失输出。H200 对应远端路径为 `lagrangian-fluid-lab/campaigns/core-v1/runtime/attempts/h200-a8-f3-mlp-seed17-v3-fullcase-reproduce-v1/20260920T054150-a87e0b7077d6/result.json`，同样成功、return code 0、无缺失输出。
- 两份 report 的 dataset、manifest、checkpoint、bundle、case denominator 和 code-closure SHA 均一致；host verification 不同。配对 helper 返回 `core.model_reproduction.comparison.v1 / compared / passed=true`。
- 比较器使用 H200 bundle 中的 `core_benchmark.py`；其实际 code closure SHA `e412e857…973c75` 与两份报告绑定值一致。当前工作树的比较代码 closure 已更新，因此没有拿新代码替旧运行结果盖章。
- 既有 per-host report 保持不可变：它们仍记录 `comparison.status=not_requested`、`cross_host_reproduction=false`。本审计把后续配对结果单独登记，不回写旧 attempt。
- 检查点是工程 preprofile update16，不是正式 32000-update 模型；formal training count 为 0，`formal_core_case_run=false`，科学状态为 `not_assessed`。仅覆盖 32 个注册案例中的一个，也没有多 seed 统计。因此 `full_product_reproduction=false`，本结果不产生 qualification credit。

本次只读取既有 Ada/H200 产物；H200 report、score 与 trajectory 临时复制至 `/tmp` 进行比较，没有重跑模型、启动 solver/queue、改动远端文件或纳入大型 trajectory 数据到 Git。后续 A8 正式复现应等待正式 checkpoint 与 Core 注册分母就绪，再按同一哈希绑定比较协议执行；这个诊断案例无需重复运行。
