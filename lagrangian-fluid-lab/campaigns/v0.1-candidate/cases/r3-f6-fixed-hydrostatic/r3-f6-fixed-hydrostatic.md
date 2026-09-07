# R3 F6 E1 固定浸没体静水力：no-run feasibility report

> 状态：**blocked_preflight_no_run**。本目录只记录门槛审计与历史日志摘要；没有为本 E1 矩阵启动 GenCase、DualSPHysics 或 GPU 求解器。
>
> `acceptance_status=not_run_not_accepted`；没有任何工况可标记为 accepted。

## 决策

mDBC 的 E0 normals/ghost 几何门槛尚未可证，因此不执行 nominal/deeper/shallower × DBC/mDBC 的 6 个主工况，也不解锁额外的 3 个 fine 工况。固定体转换也尚未形成可复用 XML：现有 DBC 与 mDBC XML 都包含 `<floatings>`，且历史 mDBC solver 明确警告 floating collision 应使用 Chrono；这与本任务的 fixed-body、无 Chrono 约束不兼容。

## 门槛审计

| gate | status | evidence |
|---|---|---|
| E0 外壳/质量静水一致性 | provisionally_near_pass_geometry_mass_only | `Vsub=0.009662575 m³` vs `m/rho=0.009750000 m³`; relative error `-0.897%`; predicted heave `-1.238 mm` |
| mDBC normal completeness | **FAIL / unproven** | baseline `792/24,335` zero `BoundNor` vectors, all 792 fixed; solver repeats `792` fixed/moving warnings |
| fixed-body semantics | **FAIL / unproven** | DBC/mDBC source XML both have `<floatings>`; no fixed-body definition or force gauge |
| Chrono isolation | **BLOCKED** | historical mDBC log warns floating mDBC collisions should use `RigidAlgorithm=3`; E1 requires Chrono disabled |

The `-0.020/-0.030 m` tank-normal-radius candidates report zero serialized normals, but they change the tank normal surface from the nominal `2.0 m` tank and were only coarse CPU diagnostics. They are not an accepted geometry repair and cannot unlock E1.

## Planned matrix (not executed)

The manifest has six primary rows; all are `blocked_preflight`, `execute=false`, with no result. The fine extension is explicitly locked, so the maximum of nine cases is respected.

| height | provisional base z [m] | boundary | body mode | status |
|---|---:|---|---|---|
| nominal | 0.611762 | DBC | fixed | `blocked_preflight` |
| nominal | 0.611762 | mDBC | fixed | `blocked_preflight` |
| deeper | 0.561762 | DBC | fixed | `blocked_preflight` |
| deeper | 0.561762 | mDBC | fixed | `blocked_preflight` |
| shallower | 0.661762 | DBC | fixed | `blocked_preflight` |
| shallower | 0.661762 | mDBC | fixed | `blocked_preflight` |

The height values are provisional plan labels derived from the existing static geometry equilibrium (`base_z=0.611761785 m`) and are not materialized as solver inputs while the gate is blocked.

## Required measurements after unblocking

Each future case must emit pressure field integrity, `Fx/Fz`, geometric displaced volume `Vsub`, and multiple tail windows (`last 0.5 s`, `last 1.0 s`, `last 2.0 s`). It must also audit fluid mass loss, body penetration/穿壁, NaN/Inf and missing fields. The proposed screening gates are:

- no unexplained zero normal vectors;
- tail mean `Fz` vs `rho*g*Vsub` within 5% (medium/fine within 3%);
- symmetric horizontal `|mean(Fx)| <= 1% mg`;
- zero mass loss and zero penetration/穿壁;
- complete pressure/force/displacement fields in every tail window.

Away from the equilibrium height, no `Fz=mg` requirement is imposed; the comparison is to the geometric displaced-volume prediction.

## Resource policy

The only GPU preflight query was `nvidia-smi -i 4,5,6,7 --query-gpu=index,uuid,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits`. It recorded the UUIDs for indices 4–7 and did not launch a solver. `gpu_indices_used=[]`, `gpu_uuids_used=[]`; GPU 0–3 were not queried or used by this task.

| index | UUID | memory used [MiB] | utilization [%] |
|---:|---|---:|---:|
| 4 | `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9` | 18 | 0 |
| 5 | `GPU-b5e3f067-fe26-4c00-5805-00a4f5acde32` | 18 | 0 |
| 6 | `GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec` | 18 | 0 |
| 7 | `GPU-88bfe7db-87fb-d458-719b-eb9a098f8f51` | 18 | 0 |

## Reused evidence

| item | path | SHA-256 |
|---|---|---|
| existing DBC Test14 XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-test14/R3_F6_test14_float1_neg074_coarse_Def.xml` | `0fe56a5b2278029dd88228ca0eab4f6702f9a0352c69b0b0bd077f4a2ca9397e` |
| existing DBC Test14 XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-test14/R3_F6_test14_float1_neg074_fine_Def.xml` | `738efe9e5035509af534a180b74a8a34e2d6f897cc4ae904fee1d7de643ccd51` |
| existing DBC Test14 XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-test14/R3_F6_test14_float1_neg074_medium_Def.xml` | `c185316949c6114de6f3616f9a05b87812704b4604b941cf516f85cc291f5d58` |
| existing DBC Test14 XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-test14/R3_F6_test14_float1_pos076_coarse_Def.xml` | `91a81fe64d55bac644271515122909f7f86e2edd3d358ab7c9163566bbbe0975` |
| existing DBC Test14 XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-test14/R3_F6_test14_float1_pos076_fine_Def.xml` | `40426ab7289c5490e84322a4a4366e9220a5019c52055d6e12af0dab2ad2b94e` |
| existing DBC Test14 XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-test14/R3_F6_test14_float1_pos076_medium_Def.xml` | `a02231118a86de98e64fdcd16828995783b4a5abf5c15de955c63980fe099df8` |
| existing mDBC preflight XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse_Def.xml` | `4693a1655e71cfdc13a61e86e8b196816352e6a1a4087f5f7585823189e9ce40` |
| mDBC zero-normal baseline XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-mdbc-zero-normal-preflight/R3_F6_mdbc_zero_normal_baseline_baseline_combined_mask2_d2_invert_Def.xml` | `ef77c127246dd015d021c92db246a7ae71237746b9a90df3461cb37aad4d5053` |
| mDBC radius-offset diagnostic XML | `lagrangian-fluid-lab/campaigns/v0.1-candidate/cases/r3-g2-f6-mdbc-zero-normal-preflight/R3_F6_mdbc_zero_normal_baseline_combined_tank_radius_minus030_Def.xml` | `f38628ae01f568ccf656d5f10df709ed4f82b244cf4d8cfd1b99ca52c0b99ddf` |
| official Float1 STL | `lagrangian-fluid-lab/campaigns/v0.1-candidate/artifacts/w05/external/test14/Float1.STL` | `f859a2e487d7cafcd119ebd680113830291f784cf736e875dce0acc88ff62cb1` |
| transformed Float1 STL, existing neg074 | `lagrangian-fluid-lab/campaigns/v0.1-candidate/artifacts/r3-g2-f6-mdbc-preflight/R3_F6_mdbc_preflight_neg074_coarse/generated/Float1_world.stl` | `b586c89a30b864447132e4e7a0c4bb982413d6b5b88cbe7b79bccfabc07c0dd5` |
| static buoyancy report | `lagrangian-fluid-lab/campaigns/v0.1-candidate/r3-g2-f6-static-buoyancy.json` | `956eb434bd6dbdf65704fc3c4e394c3f4262059f94924057a074632e07725776` |
| existing DBC Test14 report | `lagrangian-fluid-lab/campaigns/v0.1-candidate/r3-g2-f6-test14.json` | `e4555ee0b3cbab3205ca8e737ae883d225c60ab86807a0f4ebb5bcad67371c09` |
| existing mDBC preflight report | `lagrangian-fluid-lab/campaigns/v0.1-candidate/r3-g2-f6-mdbc-preflight.json` | `a011924f1a30479fca34d1fb5e986daa3e796054f445094c5248b21ec9ba49b3` |
| existing mDBC zero-normal report | `lagrangian-fluid-lab/campaigns/v0.1-candidate/r3-g2-f6-mdbc-zero-normal-preflight.json` | `7bc567f4ad2e57774485f5ec02b2586fdd826cd92956b12b1ae186a82375b4b0` |
| GPU inventory contract | `lagrangian-fluid-lab/campaigns/v0.1-candidate/w00-inventory.json` | `de28efa762450da41e102d7607517f1027439229b181982084004d9c1d513213` |

Historical raw log excerpts are in [`raw-log-summary.json`](raw-log-summary.json) and [`raw-log-summary.md`](raw-log-summary.md). The machine-readable decision is [`r3-f6-fixed-hydrostatic.json`](r3-f6-fixed-hydrostatic.json); the planned rows are [`run-manifest.json`](run-manifest.json).

## Blockers before any run

1. Produce a fixed-body XML that removes the floating/Chrono path while preserving tank, damping, gravity, domain, fluid and boundary controls.
2. Add an explicit fixed-body force measurement path and verify pressure/force sign, units and body mk target.
3. Rebuild mDBC normals with the nominal tank geometry and prove zero normals at all intended resolutions; do not use the radius-offset diagnostic as an unqualified repair.
4. Re-audit the three height placements for displaced volume, wall clearance and pressure-field completeness before unlocking the six rows.

No physical result, accepted result, or DBC-vs-mDBC conclusion is claimed by this report.
