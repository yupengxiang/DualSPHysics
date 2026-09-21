# F6 explicit-body v9 CPU/native 预检（2026-09-21）

本次是 F6 gravity/entry physical-anchor 的全新 v9 输入。v1 的 native
解码已经证明仅写 `rhopbody` 会产生错误的 body mass、COM 和 inertia；v2
随后确认 GenCase 不接受同时提供 `rhopbody` 和 `massbody`；v3--v8 则分别
保留了显式 body metadata 通过、流体离散质量和 endpoint 越界的诊断。v9
没有修改这些历史输入，也没有在同一输入上重试。

## v9 的唯一输入约定

GenCase 的 `drawbox` 包含两端的支持中心。为得到与连续体积一致的
`57×22×12=15048` 个流体中心，v9 在新 Definition 中使用：

| 项 | 值 |
|---|---:|
| 连续流体盒低角 | `(0.18, 0.08, 0.04) m` |
| 连续流体盒尺寸（质量合同） | `(1.14, 0.44, 0.24) m` |
| GenCase drawbox 尺寸 | `(1.12, 0.42, 0.22) m` |
| `dp` | `0.02 m` |
| 质量门 | `MassFluid × 原生流体粒子数` 对比 `ρ × 连续盒体积` |

这个 support-volume 约定在 `definition-contract.json` 的
`fluid.sampling_contract` 中显式登记。预检同时要求所有原生流体中心仍在
连续盒内，不能由观察到的粒子范围反推或重写连续几何。

## root review 与 CPU/native 结果

root review 通过了 gravity、显式 body metadata、边界、事件窗和新的 drawbox
绑定，但仍是 proposal-only：`T1=false`、`qualification_claim=none`、
`qualification_credit=0`，没有授权 solver canary。

一次受保护的 CPU/native preflight 随后完成：

| 检查 | 结果 |
|---|---:|
| GenCase / native decoder | 各调用一次 |
| fixed boundary | `11806` |
| floating body (`mkbound=8`) | `693` |
| fluid | `15048` |
| 原生流体质量 | `120.38400000000003 kg` |
| 连续体积质量 | `120.38399999999997 kg` |
| 相对质量误差 | `4.44×10⁻¹⁶` |
| body mass | `2.9952 kg`，相对误差 `0` |
| body COM | `(0.75, 0.30, 0.55) m`，最大误差 `0` |
| body inertia | 最大相对误差约 `2.95×10⁻⁶` |
| ID／数组／端点／速度／墙法向 | 全部通过 |

结果状态为 `cpu_native_preflight_pass_exact_one`。没有 solver、GPU、queue、
registry、ledger 或 matrix 操作；没有生成 trajectory/audit 科学产物。
这只证明 fresh Definition 可以进入**下一次独立 root 授权评审**，不构成
运行事件窗、F6 T1 或 Core 第三家族资格。

## 当前边界

下一步若要继续，只能由 root 对这份 hash-bound v9 Definition 单独授权一次
受保护 solver canary，并保留 body-state/force/torque sidecar、完整
`0–1.5 s` 事件窗和闭合边界硬门。canary 通过也不能直接登记 T1；还需完整
范围资格矩阵和 8→32 生产批次。Core completion、T1/T2 分母和 registry/ledger
在本次操作中均未改变。

证据：

- root review：`campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-root-review-v9-20260921/`
- CPU/native receipt：`campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-explicit-body-cpu-native-preflight-v9-20260921/preflight.json`
- runner：`scripts/f6_physical_anchor_explicit_body_cpu_preflight_v9.py`
- contract writer：`scripts/f6_physical_anchor_explicit_body_root_review_v9.py`
