# F2 submerged-orifice：BoundNor 分区诊断与 v2 normal remediation contract

日期：2026-09-21  
范围：只读诊断失败 anchor 的已生成 `*_Bound.vtk`，并提出全新 v2 输入身份。当前 anchor 没有被修改或重跑；没有读取或复用它的 Definition/BI4，没有调用 native decoder、GenCase、solver 或 GPU。

## 只读分区诊断

诊断只读取 generated `Bound.vtk` 中的 `Mk`、`Normal`、`NormalSize` 和 `POINTS`。法向硬阈值保持 `||Normal|| <= 1e-12 m`，不做阈值放宽。

| Mk | 角色 | 粒子数 | 零法向 | 比例 |
|---:|---|---:|---:|---:|
| 17 | 外 tank closed faces | 226,422 | 43,526 | 19.2234% |
| 18 | upper gate slab | 37,806 | 19,635 | 51.9362% |
| 合计 |  | 264,228 | 63,161 | 23.9040% |

外壁零值主要位于当前 boundary shell 的内侧层；gate 零值集中在 slab 的内侧/边缘层。该分区与当前 `GeometryForNormals vdp=-0.5`、gate 主壳 `vdp=0,1,2` 的覆盖方向一致，支持把失败归因于 normal source 与内部壳层方向不匹配。诊断 JSON：

`campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/generated-boundnor-partition-audit-v1.json`

SHA-256：`f2ea5a2db069298041d560e893ff907ae5e63eef2c86c3326ac3d23d30e7f22a`

## v2 修复合同

新身份为 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。物理 tank、source、gate 尺寸和 aperture 高度保持同一研究问题，但输入 Definition 必须逐字新建；旧 Definition、BI4、trajectory 均明确禁止复用。

合同的边界修改是：

- `GeometryForNormals` 的 outer 与 gate 都使用 `layers vdp="0"`；outer 使用 `all^top`，gate 保留六面法向和 `setnormalinvert=false`。
- outer 主壳继续使用 `vdp="0,1,2"`。
- gate 主列表先加入扩大 `dp/2` 的 `setmkvoid` precursor，再用收缩 `dp/2` 的 gate shell 和 `vdp="0,-1,-2"` 放在 solid side。
- zero `BoundNor`、zero `NormalSize`、非有限数组、ID 不闭合、外壁端点和 gate 穿透都是 hard failure；不得重试当前 anchor、放宽阈值或从 survivors 重新归一化。

候选、CPU-only proposal 和 root-review-only contract：

- [`normal-remediation-candidate-v2.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/normal-remediation-candidate-v2.json)，SHA `d653c684726bb2f5114b3a3b0f7e59e73a4733778c7c6b6c1f49b6982e8e114e`
- [`cpu-preflight-proposal-v2.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/cpu-preflight-proposal-v2.json)，SHA `9ab8e09090b91473a6f5035a01207fcfd3d573466aac317b7f16f8d0968647ee`
- [`root-review-only-contract-v2.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-only-contract-v2.json)，SHA `90c5d7bc956f1d0dce2032c6c9feb413b5aff2173b93706a7d38ce92b7125168`

三份文件互相 hash-bound，保留父 candidate、15-row matrix、完整 failure denominator、lineage、旧失败证据和诊断 adapter 的绑定。当前合同仍是 `authorized_runtime_preparation=false`；proposal 仅描述未来可能的 CPU GenCase/native decode 顺序，未执行。

## Credit 与 Core gate

完整 failure denominator 保持 15 行：planned 15、executed 0、failed 0、unattempted 15、numerator 0。当前失败 anchor 和 v2 proposal 都是 zero T1 / zero qualification / zero matrix credit；Core gate 不改变。

## 测试与实现

实现文件：

- [`f2_submerged_orifice_boundnor_partition_audit_v1.py`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_boundnor_partition_audit_v1.py)，SHA `e096c3cce51141f1a8d0333608a0a22c0d6983240506010d41ec83eb6339921c`
- [`f2_submerged_orifice_normal_remediation_v2.py`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f2_submerged_orifice_normal_remediation_v2.py)，SHA `677ab6f1c8e7345cb90a8fb6a233dc5802f39b8b28d00ecca6dc871dd6829af0`
- [`test_f2_submerged_orifice_normal_remediation_v2.py`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/tests/test_f2_submerged_orifice_normal_remediation_v2.py)，SHA `18e38b30ceb9be5f55300afd488339909cd476b7e64cf604b86dceb8d23ce2d1`

验证通过：`10 passed`，两个 adapter `py_compile` 通过，`verify-contract` 通过。没有启动 solver、GPU、queue、ledger、registry 或任何作业提交。
