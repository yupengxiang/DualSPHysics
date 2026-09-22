# F7 ComputeForces 直接扭矩观测合同（2026-09-22）

本文件只冻结官方工具语义和后续 root-review 所需的输入／输出合同，不执行 `ComputeForces`，不生成 native BI4，不启动 solver/GPU/queue。

官方帮助确认以下路径存在：

- `-onlymk:2` 筛选移动泵边界；
- `-momentaxisin` 与 `-momentaxisex` 计算内禀／外禀轴向力矩；
- `-savecsv`／`-saveascii` 输出时间历史；
- 输出包含 `ForceFluid [N]` 与 `Moment(s)`。

合同要求后续运行绑定完整 native BI4、Definition、几何、运动轴、solver 参数和时间轴，并输出：

- `pump_force_world[T,3]`；
- `pump_torque_world[T,3]`；
- `pump_torque_axis[T]`；
- 与控制 sidecar 对齐的时间轴及 `tau·omega` 能量一致性检查。

当前仍缺少 native BI4、ComputeForces 输出和 root admission，因此状态为 `root_review_only_pending_native_bi4_and_admission`，资格 credit 为 0。该合同只能解除 F7 的直接扭矩观测阻塞，不能直接授予 T1；之后仍需完成 15 行资格矩阵和 32 个生产案例。
