# F2 H2 mDBC v5 batch8 静态保持负证据审计（2026-09-21）

本报告是只读审计，不启动 solver、GPU 或 queue，不修改 registry/ledger，也不改变 Core gate。

## 结论

H2 v5 closed-cup static-hold lineage 关闭 T1 晋级：8/8 已执行行都是科学失败，7 行留在固定 15 行分母中未执行。matrix credit=0，T1_numerical=false，当前 F3/F4 Core gate 不变。

固定 observer 门槛没有改变：P95 速度≤0.1 m/s，动能/初始势能≤0.05，杯外质量≤0.0，保留率≥0.95，时域 0.6 s，末端连续保持 0.2 s。

8/8 的 static_speed_gate、static_kinetic_gate 和 no_open_cup_escape 均失败；P95 速度范围 1.57252–2.28587 m/s，动能比 0.302569–0.341538，杯外质量 0.0193424–0.0453168，stable_final_duration_s 全部为 0。

## 证据分层

8/8 worker 都是 complete_with_evidence 且 generic hard_integrity_pass=true，但 worker 的 event_window_status 都是 not_assessed。observer sidecar 对静态速度、动能、逃逸、端点和 saved-frame chord 才执行注册的静态保持合约；因此 worker 结构完整不构成静态保持通过。

CPU/native 输入闭环 8/8 通过：native_initial_zero_velocity=true、zero boundary normals=0、mass rescaling=false，且该 preflight 明确没有检查 trajectory/solver。这个结果只证明输入材料/初始状态在 native 侧闭合，不能证明运行时初始状态交接或 mDBC 壁面冲量正确。

trajectory.h5 的路径、大小和 SHA 直接沿用 observer 已记录的 immutable binding；本审计没有打开或重新哈希 HDF5，也没有重算任何同一输入。

## 两类 root-review-only 假设

1. **运行时初始静止与 mDBC 边界交接**：所有 native 输入先验静止，但八个 q/dp 组合在相同 mDBC_native、Boundary=2、-mdbc_noslip:1 下都产生静态门失败。后续新版本必须使用新的 Definition、case/output stem，并记录首个 solver frame 的速度/动能冲量和 mDBC 法向冲量；固定时域、cadence、阈值和 zero credit 规则。这个假设当前未执行，不能计入 T2。
2. **observer 合约归因分离**：把 worker 结构字段、native 初始静止字段和 observer 静态字段分栏记录，保留 not_assessed/unknown 的 zero credit。它用于区分诊断归因，不是放宽 observer 门槛，也不把当前失败轨迹改判为通过。

两类假设均为 proposal-only，均要求新的 root review。当前 H2 关闭，禁止重跑 batch8 同输入、延长时域或放宽门槛。

## 下一独立路线

保留已有 F2 submerged-orifice normal-remediation v2 作为独立拓扑的 root-review-only 候选。它有独立 candidate/contract，当前 authorized_now=false、matrix credit=0；这不是第三 T1 家族成立，也不改变分母或 Core gate。

合同：`campaigns/core-v1/cfd/f2-h2-mdbc-static-hold-negative-audit-root-review-contract-20260921.json`，SHA-256 `61f9e214c86bc7ed5c7e9b35e117c8395191af1001c2b5742b0ca9209154f4e4`。

## 8 行摘要

| cell | P95 speed (m/s) | KE/PE | outside mass | endpoint frames | chord crossings |
|---:|---:|---:|---:|---:|---:|
| 0 | 1.5725231 | 0.302971119 | 0.0193423598 | 0 | 24 |
| 1 | 1.89250092 | 0.304464957 | 0.0332158202 | 0 | 0 |
| 2 | 2.26465909 | 0.341537989 | 0.0444055944 | 2 | 17 |
| 3 | 1.6019011 | 0.302569188 | 0.0224690083 | 1 | 33 |
| 4 | 1.82104028 | 0.305996196 | 0.0331462176 | 0 | 0 |
| 5 | 2.28587158 | 0.340450799 | 0.0453168044 | 1 | 4 |
| 6 | 1.62844066 | 0.302693929 | 0.0230614973 | 0 | 24 |
| 7 | 1.83232887 | 0.305958766 | 0.0335070349 | 1 | 3 |

改动只新增本次审计的 script、JSON contract、中文报告和 regression test；不改 registry、ledger、分母或旧 trace。
