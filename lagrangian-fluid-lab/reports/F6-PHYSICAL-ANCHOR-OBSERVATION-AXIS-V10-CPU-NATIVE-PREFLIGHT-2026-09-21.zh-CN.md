# F6 v10 observation-axis CPU/native preflight（2026-09-21）

本次执行把 F6 v10 的时间语义改为 solver 报告的实际 `TimeStep` 轴，并把
`[1.0, 1.5] s` 定义为 `observation_hold`。该时间段只表示需要观察的动力学区间，
不声称刚体已经达到平衡。v10 使用全新的 Definition、GenCase XML 和 BI4；v9 的
XML、BI4、HDF5、轨迹和 solver 输出只作为版本背景，未作为输入读取。

## 执行边界

- 根审查只授权一次 CPU GenCase 和一次 native BI4 解码。
- 实际只运行了 GenCase 和 native decoder；没有运行 DualSPHysics solver、CUDA/GPU、
  runtime queue、registry、ledger 或 qualification matrix。
- `qualification_claim=none`、`qualification_credit=0`、`T1=false`；该预检不进入
  T1 分母，也不能替代完整事件窗 solver canary。
- 同一 Definition 使用 one-shot lock，禁止 retry、resume 和同输入重跑。

## 通过的输入门

新 Definition 的 `dp=0.02 m`、重力 `(0,0,-9.81) m/s²`、实体闭合面
`bottom|left|right|front|back` 和开口 `top` 均通过静态检查。native 初态为：

| 量 | 结果 |
|---|---:|
| fixed boundary particles | 11,806 |
| floating body particles | 693 |
| fluid particles | 15,048 |
| fluid mass | 120.38400000000003 kg |
| continuous-box mass | 120.38399999999997 kg |
| relative mass error | `4.44e-16` |
| body mass | 2.9952 kg |
| body COM error | 0 m |
| body inertia max relative error | `2.95e-6` |

粒子 ID 唯一、数组有限、流体和刚体初始速度均为零，粒子均位于声明的流体／刚体／
槽体范围内。预计接触窗由新定义独立重算为约 `[0.186914, 0.226914] s`。

## 结果和后续门

`preflight.json` 的状态是 `cpu_native_preflight_pass_exact_one`，但
`event_window.complete=false`，因为本次没有求解器时域输出和刚体 runtime sidecar。
下一步若继续，必须以这些 fresh 输入为基础重新进行独立 root review，再最多授权一次
CPU solver canary；solver 实际时间间隔、末端覆盖、接触／穿透、开口质量流和观察窗完整性
仍需逐条硬审计。v9 的 cadence 失败证据保持不可变，不能由 v10 预检改判为通过。

证据：[v10 preflight receipt](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-cpu-native-preflight-20260921/preflight.json)、
[fresh Definition contract](../campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-observation-axis-v10-root-review-20260921/definition-contract.json)。
