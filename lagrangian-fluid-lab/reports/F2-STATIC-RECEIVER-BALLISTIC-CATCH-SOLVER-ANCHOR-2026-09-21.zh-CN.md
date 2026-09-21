# F2 静态接收盆 solver anchor 后审（2026-09-21）

这次记录包含一次执行器基础设施失败和一次允许的修复重试。两次使用完全相同的 F2 Definition、GenCase XML/BI4、solver、时间窗和输出 cadence；重试只修复官方动态库路径，不改变科学输入或门槛。

## 第一次尝试：基础设施失败

原始 job `f2-static-receiver-ballistic-catch-q05-anchor-v1` 在 solver 进程加载阶段退出，返回码为 `127`，日志明确为找不到官方 `libdsphchrono.so`。没有生成 solver 帧，没有执行科学计算；该 attempt 保留为执行器失败，信用为零。

根据计划中“已有证据的基础设施故障允许一次同输入修复重试”的规则，建立了单独的 infra-retry root review。修复内容只有 worker 的 `LD_LIBRARY_PATH` 绑定；Definition、原生输入、观察窗、阈值、分母和 output stem 均没有改动。重试仍禁止 registry、matrix 和任何资格信用。

## 修复重试：raw solver 完成但科学硬门失败

重试 job `f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1` 在 Ada GPU 上正常结束，Run.out 记录 `TimeMax=1.5`、`TimePart=0.005`、`Finished execution (code=0)`。原生 raw 输出有恰好 **301** 个帧，编号 `Part_0000` 到 `Part_0300`，对应 `0–1.5 s` 的登记窗口；raw 数据约 1.57 GB。

独立后审 [postrun-audit.json](../campaigns/core-v1/runtime/attempts/f2-static-receiver-ballistic-catch-q05-anchor-infra-retry-v1/20260921T111854-b642c199de99/product/postrun-audit.json) 读取首帧、末帧及每 60 帧的固定样本。样本的 native ID 唯一、数组有限、外槽闭合面端点数为 0；但 Run.out 明确报告：

- `Excluded particles = 64`；
- `Excluded particles due to Density = 44`；
- 从约第 120 帧起流体 ID 数由 18,432 变为 18,368。

排除粒子门是预登记的硬完整性条件，因此后审状态为 `raw_solver_complete_scientific_hard_failure`、`hard_integrity_pass=false`。没有删帧、补粒子或按幸存者重新归一化；事件窗口和材料路径没有继续解释为通过。

## 结论

该 F2 scope 的 anchor 只证明了输入物化、solver 启动和原生输出链路可运行，不能支持 T1 资格。第一次 loader 失败和第二次排除粒子失败都已保留；同一科学输入禁止再次重试，父 scope 的 15 行分母仍为零信用。若未来重新做 F2，必须提出新的、可证伪的物理／数值假设和新的输入身份，先重新 root review；不能把本次 raw 完成改写为资格证据。
