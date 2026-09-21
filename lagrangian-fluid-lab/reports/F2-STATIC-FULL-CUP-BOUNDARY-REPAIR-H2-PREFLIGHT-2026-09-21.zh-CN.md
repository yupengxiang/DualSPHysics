# F2 静态 full-cup H2 CPU/native canary（2026-09-21）

本记录只覆盖 root review 授权的一次新输入 canary，不是 F2 的 T1 资格或生产批次。H2 保留连续杯体、Boundary=2 的 mDBC／显式几何法向和 0.60 s 规定窗口，只改变初始液体晶格：对杯底及四个闭合侧面使用

\[
c(dp)=3\,hdp\,dp=0.039\,\mathrm m,
\]

并由原登记体积 `V=0.022950 m³` 反算新 footprint 内的液面高度。case identity 为 `CORE_F2_static_full_cup_volume_supportclearance_h2_q0p00000000_dp0p010000000000_canary`，revision 为 `F2_static_full_cup_support_clearance_h2_v1`；旧 Definition、旧轨迹和旧 BI4 均未复用。

## 执行和结果

- fresh Definition、zero-angle motion 和 hash receipt 已写入 `campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/input/`；只运行 CPU GenCase 一次。
- 首次 native decoder 调用因脚本没有预先创建 `decoded/` 父目录而发生基础设施失败。创建目录后只对已有 BI4 做了一次恢复解码；没有重跑 GenCase，也没有 scientific same-input retry。
- 生成流体数 `23,100`，总粒子数 `205,248`；ID 唯一，位置／速度／密度有限，初始速度为零。
- 最小杯体闭合面距离 `0.040 m`，满足 `c=0.039 m`；初始端点计数为零，`BoundNor` 为 `0` 个零法向。
- 原生质量 `23.100 kg`，连续声明质量 `22.950 kg`，相对误差 `0.00653595`，通过预登记的 `0.03` 门。

回执在 [preflight.json](../campaigns/core-v1/cfd/f2-static-full-cup-boundary-repair-h2-cell0-v1/preflight.json)，其中保留第一次基础设施错误、恢复次数、命令输入和全部哈希。结果是 `cpu_native_preflight_pass`，但 `qualification_claim=none`、`qualified=false`、`T1_numerical=false`、`matrix_credit=0`。固定 15 行分母只记为 `executed=1, passed=1, unattempted=14`；不允许据此扩展矩阵、启动 solver/GPU 或修改 registry/ledger。

这个结果只说明 H2 输入通过 CPU/native 初始状态门，不能说明静态保持、事件窗完整性、流体边界稳定性或第三家族 T1。下一步若要继续，必须另行 root review 授权 solver canary；当前 F2 仍没有资格信用。
