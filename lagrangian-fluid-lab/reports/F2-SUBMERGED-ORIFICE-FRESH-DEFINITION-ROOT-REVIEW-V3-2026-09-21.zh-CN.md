# F2 submerged-orifice：fresh literal Definition 与 root-review-v3

日期：2026-09-21  
范围：仅生成和静态审查全新 v2 Definition；没有运行 GenCase、native decoder、solver、GPU，也没有修改旧 anchor 或复用旧 Definition/BI4。

## Fresh Definition

writer 从字面常量直接生成新 XML，case identity 为 `F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。静态 XML contract 核对通过：

- `GeometryForNormals` 的 outer/gate 均为 `vdp=0`；outer 为 `all^top`，gate 为六面体。
- mainlist 先写 outer `0,1,2`，再写 expanded `setmkvoid` gate precursor，最后写 solid-side gate `0,-1,-2`。
- mDBC `normals active=true`、`distanceh=3.0`、`svshapes=true`；Boundary/SlipMode/NoPenetration 为 `2/1/1`。
- 只写 Definition；fresh generated XML、BI4 和 preflight 均不存在。

文件与 SHA：

- [`F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2_Def.xml`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/fresh-definition-v2/F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2_Def.xml)：`1ff8cd118f31fc3a05c4e538c72c43f0b036cd0b640d597d9e2ca534d10d6e81`
- [`fresh-definition-proposal-v2.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/fresh-definition-proposal-v2.json)：`5d740d09add150d213c6ed034cf6f433880039688231271b3258edaaded7fd65`
- [`fresh-definition-contract-v2.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/fresh-definition-contract-v2.json)：`0ad110108f76394af9778af08d8b5ddbc33eabbe0bd1ec04d45bb8f724aa0f94`

## Root-review-v3

[`root-review-receipt-v3.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-receipt-v3.json) 的 SHA-256 为 `789ba8e926e266f324f57f4ce2d066a6493c9ce218ba53d6c9dabf7f1252eebb`。

v3 静态审查通过并 hash-bound 了 fresh Definition、proposal、contract、writer、writer test、v2 candidate/proposal/contract、BoundNor audit、父 matrix/denominator/lineage 和失败 anchor preflight。decision 为 `fresh_definition_static_review_passed_cpu_native_still_closed`；`authorized_for_one_fresh_cpu_native_preflight=false`。剩余阻塞只有尚未执行新 Definition 的 GenCase/native preflight，因此本 receipt 不授权 CPU/native。

完整 denominator 仍为 planned 15、executed 0、passed 0、failed 0、unattempted 15、numerator 0；T1、qualification、matrix credit 均为 0，Core gate 不变。未来若另行授权，只能是该新 case 的单次 CPU GenCase/native decode，并继续要求 zero normal count 为 0（`||Normal|| <= 1e-12 m`）；solver、GPU、queue、ledger、registry 仍禁止。

## Tests

```text
.venv/bin/python -m pytest -q \
  tests/test_f2_submerged_orifice_definition_writer_v2.py \
  tests/test_f2_submerged_orifice_definition_root_review_v3.py \
  tests/test_f2_submerged_orifice_normal_remediation_root_review_v2.py \
  tests/test_f2_submerged_orifice_normal_remediation_v2.py \
  tests/test_f2_submerged_orifice_preflight_v1.py \
  tests/test_f2_submerged_orifice_scope_v1.py
```

结果：`19 passed`。writer/v3 adapter `py_compile`、Definition contract verification 和 v3 receipt verification 均通过。

实现 SHA：

- `f2_submerged_orifice_definition_writer_v2.py`：`b88c7e53bf377b4dd12e3df575f2264113be7b85da8375c597f23c47717df1ea`
- `f2_submerged_orifice_definition_root_review_v3.py`：`67a55a9493642986b1a1f062947e9cb3d22cb665c8c66266a3ec00fc9877ee79`
- `test_f2_submerged_orifice_definition_writer_v2.py`：`be8ecd614375f158f69cfc2218af1a8d4e7605cf630a316d83f8b39daba62215`
- `test_f2_submerged_orifice_definition_root_review_v3.py`：`53dd3b3847a20b1806002e58e7bf22596516fd53631a33e22e3c8fb13a0e3916`
