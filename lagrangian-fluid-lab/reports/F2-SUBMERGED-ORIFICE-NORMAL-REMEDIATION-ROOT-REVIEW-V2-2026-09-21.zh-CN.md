# F2 submerged-orifice normal-remediation-v2：只读 root review

日期：2026-09-21  
审查范围：v2 candidate、CPU-only proposal、BoundNor 分区 audit、父 scope 的 matrix/failure denominator/lineage、失败 anchor preflight，以及全部 adapter/test SHA。审查过程没有调用 GenCase、native decoder、solver、GPU、queue、ledger 或 registry，也没有修改旧 anchor。

## 审查结论

父 scope 的 15 行 matrix、完整 failure denominator、lineage 和旧失败输入边界均通过 hash 重核。失败 anchor 的 `preflight_pass=false`、`matrix_credit=0`、`qualification_claim=none` 且 zero `BoundNor=63,161`；v2 分区 audit 与该计数一致，Mk17/Mk18 分区分别为 43,526 和 19,635。

v2 candidate、proposal 和 root-review-only contract 的 hash 均通过，且 proposal 保持新 case identity：`F2_ORIFICE_q0p50_dp0075_spatial_normalremediation_v2`。但是 v2 目前只有 recipe/proposal，没有 hash-bound 的 fresh literal Definition writer，也没有 fresh generated XML、native BI4 或 CPU/native 结果。因此本次不授权 CPU/native preflight。

root-review receipt：

[`root-review-receipt-v2.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/normal-remediation-v2/root-review-receipt-v2.json)

SHA-256：`c57914722d8a08916252b0e4c445e09d8a93401033e845dcb8d1fad66358aa6f`

receipt decision：`not_authorized_pending_fresh_definition_writer`。所有 runtime/protected-state 权限保持关闭。

## Hash-bound 输入

- v2 candidate：`d653c684726bb2f5114b3a3b0f7e59e73a4733778c7c6b6c1f49b6982e8e114e`
- v2 CPU proposal：`9ab8e09090b91473a6f5035a01207fcfd3d573466aac317b7f16f8d0968647ee`
- v2 root contract：`90c5d7bc956f1d0dce2032c6c9feb413b5aff2173b93706a7d38ce92b7125168`
- BoundNor partition audit：`f2ea5a2db069298041d560e893ff907ae5e63eef2c86c3326ac3d23d30e7f22a`
- parent fixed matrix：`d3a275b6e6dc130bdf249f6d01a69d54c7f651831dd6a6ea289f70fd18c916eb`
- parent failure denominator：`cc34093a811db4a23edab3cf6e8dfc7ec5c01bb391eabe38b539ac55fb2edbc3`
- parent lineage：`42dbbe2181096855175110f74de6a997f37d3c5e23c7dcbb75be8d3406dd0e69`
- failed anchor preflight：`a29673207eba9cf2d3e62ad3693a0224b749e3cdfc95a9c50eb5733d375837dc`

Adapter/test SHA 也已绑定：v2 root-review adapter `54ec0fd39b84958fe49e380d0f08d9470b0078e846637191e5fe9d3664bccbfe`、v2 partition adapter `e096c3cce51141f1a8d0333608a0a22c0d6983240506010d41ec83eb6339921c`、v2 remediation adapter `677ab6f1c8e7345cb90a8fb6a233dc5802f39b8b28d00ecca6dc871dd6829af0`、v2 root-review test `44d6b14f3cffb6aa8cee7c08f1c130861201d10a12ba69dbdec638603c83abc2`，以及父 scope/preflight adapter 与 tests。

## 阻塞与后续条件

阻塞项是输入闭合而非数值阈值：

1. 需要实现并 hash-bind 一个写出全新 v2 literal Definition 的 adapter。
2. 需要新的 root review 审核该 writer 后，才可授权一个且仅一个 q=.5、dp=.0075 的 CPU GenCase/native decode preflight。
3. 新 preflight 必须保持 `zero_normal_count==0`（`||Normal||<=1e-12 m`）、`NormalSize` 无零值、ID/有限值/质量/geometry hard gates 全部通过；任何失败都维持 zero credit。

failure denominator 仍为 planned 15、executed 0、passed 0、failed 0、unattempted 15、numerator 0；T1、qualification、matrix credit 均为 0，Core gate 不变。

## 测试

```text
.venv/bin/python -m pytest -q \
  tests/test_f2_submerged_orifice_normal_remediation_root_review_v2.py \
  tests/test_f2_submerged_orifice_normal_remediation_v2.py \
  tests/test_f2_submerged_orifice_preflight_v1.py \
  tests/test_f2_submerged_orifice_scope_v1.py
```

结果：`13 passed`；root-review adapter `py_compile`、`verify-receipt` 和父/v2 contract verification 均通过。
