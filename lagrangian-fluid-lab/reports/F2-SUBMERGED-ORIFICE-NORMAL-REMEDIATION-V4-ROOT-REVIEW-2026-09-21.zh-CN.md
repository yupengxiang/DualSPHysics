# F2 submerged-orifice normal remediation v4 root-review-only audit

状态：**全新静态候选；运行权限关闭；无 qualification/matrix credit**。

v3 的固定 CPU/native preflight 已闭合失败：83,443 个 BoundNor 与 NormalSize 零值，outer Mk=17 为 64,899、gate Mk=18 为 18,544；ID/finite/端点门通过，但源质量误差为 -4.207502092633919%。

唯一 v4 假设是一个完整 literal recipe：将 GeometryForNormals 的 outer/gate vdp 分别从 v3 的 `0,1,2`/`0,-1,-2` 镜像为 `0,-1,-2`/`0,1,2`，并将源框端点修正为预测 86×56×48 格点。预测离散质量误差为 +0.78125%；这只是待证伪预测。

若未来经独立 root review 后执行的 exact-one CPU/native preflight 任一 zero-normal、finite/ID、端点或质量门失败，则 v4 被证伪，F2 normal-remediation 路线暂停；不得放宽门槛、重试同输入或授予 credit。

所有 GenCase、native decoder、solver、GPU、job、queue、ledger、registry、matrix 权限均关闭。

Contract status: `root_review_only_static_contract_runtime_closed`。

## Hash closure

- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/root-review-only-contract-v4.json` SHA-256 `b15c66507baeefd9b5ccd44dcc51167f57103d35473224efdacfec18030ce739` (8685 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/normal-remediation-candidate-v4.json` SHA-256 `a80e1f91bb31575c6967bb02f5daf69fdb161edd98a1f0eb7ccfdabbbbe0bce6` (9497 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/v3-failure-evidence-v4.json` SHA-256 `3feb5e40483b5f3893a4254c4833ccfe8c591c14f81e12923b28dfe4357dabfa` (5718 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v4/fresh-definition-v4/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v4_Def.xml` SHA-256 `a138d65a9a87acea2664eb640ebd74bca06f8890259fb93a7224ea582d52fd07` (3721 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_normal_remediation_v4.py` SHA-256 `22ca462a83f11d9f92db46650553156630b1a907110cc9c74f77dc9d9024eae4` (37804 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-v3/preflight.json` SHA-256 `90b8c460262ad1424aab42dbc0046f1bf3b511478ddc0b5e240fd83b87485dd7` (13017 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-v3/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3_Bound.vtk` SHA-256 `cac3d1efb795869e5f296c962b9719800b7b281a7eb43114569f0cb6c1f25eae` (11004255 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-v3/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3_hdp_Actual.vtk` SHA-256 `8cc76e435083e50229728a06b332fb2308afabd4c3f510edfed52436bba3c246` (1680 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/preflight-v3/gencase.log` SHA-256 `900212cf5b3793f2215d86b2492eb74d04a1b05601a50ca6d1d68d2ad598fba0` (6090 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/fresh-definition-v3/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3_Def.xml` SHA-256 `a8db3f6f3d5d47851e30e005daa4d0b3434630c78f70446428fe56710234c6da` (4798 bytes)
- `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_submerged_orifice_normal_remediation_v4.py` SHA-256 `1180120c76c88836b96ea9600af2e967f33ab19e4cb878de91df784e7ebcf62a` (4427 bytes)
