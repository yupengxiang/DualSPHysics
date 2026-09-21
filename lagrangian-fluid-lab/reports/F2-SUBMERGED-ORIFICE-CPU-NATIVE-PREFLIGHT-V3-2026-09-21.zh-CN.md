# F2 submerged-orifice v3 CPU/native preflight

状态：**exact-one CPU GenCase/native decode 已执行，hard audit 失败，立即停止，credit=0**。

执行 case 为 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3`，唯一输出 prefix 为 `normal-remediation-v3/preflight-v3/`。本次没有重试，没有读取或复用 v4 Definition/BI4，也没有启动 solver、GPU、job、queue、ledger、registry 或 matrix submission。

GenCase 成功生成 `475,631` 个粒子，其中 boundary `255,906`、fluid `219,725`。native decode 成功，IDs 与 generated XML 对齐且数组有限；外壁 endpoint 为 `0`、gate penetration 为 `0`。

硬门结果：

- `zero BoundNor = 83,443`，要求 `0`，失败。
- `zero NormalSize = 83,443`，要求 `0`，失败。
- native mass `92.696484375 kg`，连续质量 `96.768 kg`，相对误差 `-4.207502092633919%`，门槛 `2.5%`，失败。
- GenCase log 报告使用 `33 shapes`，非零法向 `172,463/255,906`，最终 zero normals `83,443/255,906`。

因此 `preflight_pass=false`、`qualification_claim=none`、`matrix_credit=0`。receipt 的 CPU/native 权限只消耗了这一次受限预检；其 solver/GPU/job/queue/ledger/registry/matrix 权限仍为关闭状态。

## Hash closure

- [root-review receipt](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/root-review-receipt-v3.json) — `adce91758b4d564f3a95db8c61df4248899c3534905198a968700458582819b5`
- [preflight contract](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-contract-v3.json) — `8d9e1b03336e87d7e88ac34281c82227791b4d886487e0bc7b7000cc92f4f25a`
- [fresh Definition](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/fresh-definition-v3/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3_Def.xml) — `a8db3f6f3d5d47851e30e005daa4d0b3434630c78f70446428fe56710234c6da`
- [v3 runner](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_preflight_v3.py) — `155e032114cc263d7c6c6859ea30c167657d8fc60962ee8be7222fe8463bb125`
- [v3 preflight test](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_submerged_orifice_preflight_v3.py) — `6139f70a5e26ce8117cb33e55d3d557f8762dbc6c4c7a4dd146cbf8be939d2bc`
- [preflight receipt](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-v3/preflight.json) — `fdeb1a55c93f72a869a7faeb7b1a87aa3ccb374eb127897c282db724dbab9249`
- `gencase.log` — `900212cf5b3793f2215d86b2492eb74d04a1b05601a50ca6d1d68d2ad598fba0`
- generated XML — `4bc5595843b50cd458ef322f2c777959f4f448fbe7b871c4408e59a2abe1ee6c`
- generated native input — `a0515e0416acd36987f2e6f889f5ec74e92a4d1f2fccf31a94d58fe4876445ce`
- generated Bound.vtk — `cac3d1efb795869e5f296c962b9719800b7b281a7eb43114569f0cb6c1f25eae`

Static contract tests passed `5` cases before the exact-one runtime. The failed receipt is final evidence for this input; no further runtime action is authorized by this report.
