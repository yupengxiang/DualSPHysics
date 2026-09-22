# F1/F2 第三 T1 家族路线审计（2026-09-21）

本次只读审计先核验 F1，再核验 F2 receiver/overflow-weir。F1 的 H1/H2 修复线已有明确停止结论，悬空障碍物 anchor 也以完整事件窗口记录了 hard-integrity 失败；F2 receiver/weir 的 q=.5 anchor 同样保留 hard-integrity 失败和 event-censored 结果。因此没有重跑同一输入，也没有把失败者从分母删除。

选择的最小下一步是独立拓扑的 F2 submerged-orifice normal-remediation v2 静态合同：原始 q=.5 CPU/native 输入有 63161 个 zero boundary normals，v2 新 Definition 已完成 hash-bound 静态审查，但还没有新 v2 XML/BI4，且 v3 root receipt 明确未授权 CPU/native。下一步只能先获得单独 root review，再考虑一个新 output stem 的 CPU/native preflight；本合同不授权执行。

## 现有路线结论

- F1：`qualified=false`、`T1_numerical=false`；H1 canary hard-integrity=False，F1 G1 anchor hard-integrity=False，事件窗口虽完整也不能挽救 hard failure。当前 repair lineage 的 blocker 是 H1/H2 stop/no same-class retry。
- F2 receiver/weir：15 行中 `executed=1`、`failed=1`、`event_censored=1`、`unattempted=14`、`matrix_credit=0`；hard-integrity=False，event complete=False，weir penetration particle frames=1490604。该 route 关闭为负证据，不重试。

## 选定合同边界

- candidate：`F2_submerged_orifice_normal_remediation_q0p5_anchor_v2`，case：`F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。新 output stem：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/fresh-definition-v2/generated/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。
- 先审查 v3 static root receipt；本轮 `definition_writer/cpu_gencase/native_decode/solver/gpu/queue/ledger/registry` 全部关闭，资格 credit=0。
- 若未来得到独立授权，只能按 fixed hard gates 检查 zero BoundNor、normal size、finite/ID、native mass 和 wall/gate endpoint；失败或 event-censored 继续留在 15-row denominator，不能放宽阈值、重标输入或 survivor renormalization。

## 产物与 SHA-256

- audit/contract：`campaigns/core-v1/cfd/f1-f2-third-t1-route-audit-v1.json`（运行脚本后读取该文件计算 SHA）。
- implementation：`scripts/f1_f2_third_t1_route_audit_v1.py`，SHA `a2a605a48b92a207f7f16a15ffa31800b7a531c0614281b5d556795c16f3a070`。
- contract 的 `hash_bindings` 保存 F1 资格/失败证据、F2 receiver terminal denominator、orifice parent matrix/denominator、v2 candidate/Definition/root receipt/preflight contract 的当前 SHA 和字节数。

Core gate 结论：`third_t1_family_established=false`、`qualification_credit_added=0`、`core_gate_changed=false`；registry/ledger mutation 均为 0。
