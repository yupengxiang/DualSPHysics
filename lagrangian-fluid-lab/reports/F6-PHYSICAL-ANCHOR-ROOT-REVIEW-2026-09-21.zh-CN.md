# F6 gravity physical-anchor root review（2026-09-21）

本次产物是 F6 的 root-review-only physical-anchor proposal。它只生成一份全新的 Definition、几何/质量/惯量 contract、body-state/force/torque sidecar schema、事件窗 contract 和 CPU preflight receipt；没有调用 GenCase、solver、GPU 或 queue，也没有写 registry、ledger、matrix。proposal 的 `qualification_claim` 为 `none`、`qualification_credit` 为 `0`、`T1=false`。

## 新输入和物理锚点

Definition 由 `scripts/f6_physical_anchor_root_review.py` 中的新常量从零生成，identity 为 `CORE_F6_physical_anchor_single_body_gravity_20260921`，body identity 为 `F6_physical_anchor_body_beta_20260921`，`mkbound=8`。旧 F6 floating-box、heavy-box-entry、twin-floaters 的 XML/HDF5，以及 zero-force W0 Definition，只作为 hash-only provenance；`old_xml_copied=false`、`old_bi4_reused=false`、`old_hdf5_reused=false`，没有作为输入。

本路线明确使用 `gravity=(0,0,-9.81) m/s²`，`dp=0.02 m`，流体密度为 `1000 kg/m³`，刚体密度为 `780 kg/m³`。新 tank 尺寸为 `1.50×0.60×0.90 m`，底、左、右、前、后面封闭，顶面开放。流体区域为 `(1.14×0.44×0.23) m`，初始自由液面 `z=0.28 m`。单刚体尺寸为 `0.20×0.16×0.12 m`，初始 COM 为 `(0.75,0.30,0.55) m`，初速度和角速度均为零。

刚体体积为 `0.00384 m³`，质量由密度和体积得到 `2.9952 kg`。以初始 body axes、COM 为惯量参考点，惯量张量为

```text
diag(0.009984, 0.01357824, 0.01637376) kg·m²
```

这个 zero-initial-velocity、gravity-driven entry 设计只用于判断一次受保护 canary 是否值得授权。先前的 zero-force W0/W1 anchor 只能验证 Definition、单位、几何和惯量接口，不能替代本物理路线的资格证据。

## CPU 预检和可审计事件窗

当前 receipt 为 `cpu_physical_anchor_preflight_pass`。检查覆盖 XML 解析、无旧资产输入 token、精确重力和 `dp` 绑定、body 密度/`mkbound`、TimeMax/TimeOut、质量、惯量正定性、初始 tank 内部位置、初始接触间距、解析事件以及 sidecar/event contract。

输出窗口固定为 `0.0–1.5 s`，cadence 为 `0.005 s`，预期 `301` 帧，最后的 settle hold 为 `[1.0,1.5] s`。基于刚体下缘到自由液面的解析自由落体估计：

- 预计初始液面间隙为 `0.21 m`；
- 预计接触 COM 高度为 `0.34 m`；
- 预计接触时间为 `0.2069141263 s`，接触预测窗为 `[0.1869141263,0.2269141263] s`；
- 预计入水速度约 `2.0298275789 m/s`；
- 以密度比得到的静态浸没比例为 `0.78`，解析平衡位置的底面和顶面 clearance 分别为 `0.1864 m` 和 `0.5936 m`，均高于 `3*dp`。

这些是 geometry/gravity 的可审计预测，不是 solver 结果；实际 hydrodynamic response、接触记录和 settle hold 仍标为 runtime unknown。事件窗只有在 runtime sidecar 完整产生、时间严格递增、body identity 每帧存在、body/force/torque 值有限、闭合面无接触/穿透、顶面无未解释质量通量且 `[1.0,1.5] s` 未删失时才能完成。

sidecar schema 要求每帧记录 `time_s`、`body_position_m`、`body_quaternion_xyzw`、线/角速度、`fluid_force_N`、`fluid_torque_Nm`、`contact_count`、`penetration_depth_m`、`boundary_contact_count`、`open_face_mass_flux_kg_s`、`event_status` 和 `valid`。流体力和力矩与重力/体重分开；闭合 tank 面接触和开放顶面通量分别记录，body_id 是不可变 identity。

## root review 决定和边界

在当前 CPU receipt 条件下，事件窗在解析层面可审计，建议为：`worth_one_protected_solver_canary_conditionally`。这只是 root-review 建议，不是执行授权：`solver_canary_authorized_now=false`。若 root 后续授权，最多一次 protected solver canary，必须锁定本 proposal 的 hash-bound Definition、event contract 和 sidecar schema，禁止同输入 retry、禁止 matrix/registry/ledger 扩展，并保留失败时的 body-state/force/torque 证据。

任何 gate 失败、事件窗删失、缺少 body identity/状态侧车、闭合边界接触或未解释开放面质量通量，都使 canary 结果不可用；应保留失败 receipt，保持 credit 为零，不通过重跑或矩阵扩展补救。当前没有声称 F6 qualification、Core 第三 T1 family 或任何 T1 credit。

对应文件位于 `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921/`：Definition、`definition-contract.json`、`event-window-contract.json`、`body-state-force-torque-sidecar-schema.json`、`preflight.json`、`proposal.json`。本报告和这些文件只描述静态/root review 材料，未启动任何重型任务。
