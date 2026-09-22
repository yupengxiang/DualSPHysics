# F7 泵循环角动量诊断（2026-09-22）

本次只读取现有隔离 canary，不启动新的 GenCase、native solver、GPU 或 queue，也不修改 registry、ledger、matrix、denominator 或 completion。

诊断绑定：

- 流体轨迹：`campaigns/core-v1/evidence/f7-pump-runtime-canary-dp0020-t0p55/trajectory.h5`
- 控制 sidecar：`campaigns/core-v1/evidence/f7-pump-runtime-canary-dp0020-t0p55/control-sidecar.h5`
- 两者时间轴相同，12 个原生帧，流体粒子身份唯一且数组有限。
- 泵轴为单位向量 `[0, 1, 0]`；第 10 帧开始出现非零规定角速度。

将每帧流体角动量投影到泵轴，并对保存帧作有限差分，得到运动期间最大角动量响应代理约 `0.0171626558`（单位为由输入质量、位置和速度决定的组合量）。这说明 canary 中确实能观察到非零规定运动和流体状态响应。

但这不是壁面反作用扭矩：轨迹没有泵体受力／扭矩数据，响应代理还受到保存 cadence 和早期流体瞬态的影响。因此以下门仍然关闭：

- `direct_torque_dataset_present=false`
- `torque_provenance_verified=false`
- `pump_independence_gate=false`
- `T1_numerical=false`
- `qualification_credit=0`

结论：该诊断可以作为后续 root review 的补充观测，不能把 F7 canary 升级为第三 T1 family，也不能授权 Definition、preflight、solver 或正式训练。现有 F7 阻塞仍需要可追溯的非零扭矩数据及其能量／几何 provenance，随后才可重新评估它是否独立于 F6。
