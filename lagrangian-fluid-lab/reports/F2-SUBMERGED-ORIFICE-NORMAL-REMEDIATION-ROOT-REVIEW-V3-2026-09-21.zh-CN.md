# F2 submerged-orifice normal remediation v3 root review

本报告是独立静态 root review receipt 的中文报告。v4 failure audit、v3 candidate、fresh Definition、writer/audit adapters、测试以及父 scope 闭合文件均重新 SHA 校验通过。

审计证据显示 v4 的 64,899 个 zero `BoundNor/NormalSize` 全部在外壁 `Mk=17`，闸板 `Mk=18` 为 0；v4 源粒子数为 86×57×49=240,198，质量误差为 +4.718017578125%。v3 只提出一个几何/法向闭合假设：GeometryForNormals 镜像活动 shell 层，并将 source lattice 静态收敛为 86×56×48=231,168。

由于全部输入闭合，receipt 只授权一个全新 v3 case 的 CPU GenCase 与 native decode。solver、GPU、job、queue、ledger、registry、matrix submission 均关闭；zero-normal 必须为 0、NormalSize 必须为 0、数组/ID/端点和 mass≤2.5% 门槛保持不变。

授权 case：`F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3`；matrix index：`4`；当前仍未执行 runtime，credit=0。

## Hash closure

- `v4_preflight_evidence`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/preflight-v4/preflight.json` SHA-256 `90123f1c0ab3b776a306729c92d1d5dbb6281190e19511245a724f83036e1113` (10171 bytes)
- `v4_boundnor_failure_audit`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/v4-boundnor-failure-audit-v1.json` SHA-256 `56960219cc28687d5e7233f48485f242b014082c3b965f7f9eee1f2f6742ca47` (7839 bytes)
- `v4_failure_audit_adapter`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_v4_failure_audit_v1.py` SHA-256 `b189aa69dd8b8fd9cfb0bbecae0d5f0bd81ca75b94a711ea7afe53ac0939e74c` (12156 bytes)
- `v3_candidate`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/normal-remediation-candidate-v3.json` SHA-256 `0368f5fdc11b089cad3664f9c8c1d2f88a645165c5233774e7f90b4704de8852` (7842 bytes)
- `v3_fresh_definition`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/fresh-definition-v3/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v3_Def.xml` SHA-256 `a8db3f6f3d5d47851e30e005daa4d0b3434630c78f70446428fe56710234c6da` (4798 bytes)
- `v3_static_contract`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v3/root-review-only-contract-v3.json` SHA-256 `f1927012839fd9c84cf8d13a3d6ebea6c251ca9d6d9f8d1cbfb2107378413e18` (8193 bytes)
- `v3_writer_adapter`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_normal_remediation_v3.py` SHA-256 `c2c03bf543a03d181769661ed34d07a6d8d643684222a0ddf465ed460df0d2db` (39709 bytes)
- `v3_contract_test`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_submerged_orifice_normal_remediation_v3.py` SHA-256 `4ac63eee47f5ee48475a5a16ece62f8ea64667a58a31562c456b65fe264001df` (5449 bytes)
- `parent_fixed_matrix`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/fixed-matrix-v1.json` SHA-256 `d3a275b6e6dc130bdf249f6d01a69d54c7f651831dd6a6ea289f70fd18c916eb` (5910 bytes)
- `parent_failure_denominator`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/failure-denominator-v1.json` SHA-256 `cc34093a811db4a23edab3cf6e8dfc7ec5c01bb391eabe38b539ac55fb2edbc3` (691 bytes)
- `parent_lineage`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/lineage-clarification-v1.json` SHA-256 `42dbbe2181096855175110f74de6a997f37d3c5e23c7dcbb75be8d3406dd0e69` (2735 bytes)
- `parent_root_contract`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/root-review-contract-v1.json` SHA-256 `285f3bd5eef0e71ffe277afc73954627bc64694cf78879c9bb0df39694cc34f6` (4978 bytes)
- `scope_adapter`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_scope_v1.py` SHA-256 `8b697c3e2a8f23cfe1b0a36b0d699e060f6d876027057621becb3160b1343cb9` (28237 bytes)
- `scope_test`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_submerged_orifice_scope_v1.py` SHA-256 `4ab3040ad08afc1cd092b3305a240a080952a3c797a85f6cd8151d022e43511a` (3151 bytes)
- `v3_root_review_adapter`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_normal_remediation_root_review_v3.py` SHA-256 `ff6d89822caffb28fe702391d9c4f062e9f3799fe2be659c0ed46a5e99485eee` (27359 bytes)
- `v3_root_review_test`: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_submerged_orifice_normal_remediation_root_review_v3.py` SHA-256 `1d7b660b0d2fb6a479f44fc7657617d3193bf816e710f2a7da5e6798dfc5b666` (4230 bytes)

Receipt SHA-256 `5672f5d8533fd7f73f30feddc8de106f2aa348dac29563d785dfebfe46773169` (9956 bytes)
