# F2 submerged-orifice transfer 路线审计（2026-09-21）

本轮审计保留了已有失败证据：F2 receiver/overflow weir anchor 的 hard integrity 已失败并出现大量 weir penetration/crossing；F1 G1 悬空障碍物 anchor 也已 hard-integrity 失败；F2 rotating-cup DBC duration 路线只能作为 event-censored negative evidence。上述输入、Definition、BI4、trajectory 与失败行均不重跑、不改名、不提供资格 credit。

在这些约束下，新增候选 `F2_submerged_orifice_transfer_v1`。它研究固定上部闸板下的低位 submerged aperture：静止上游液库在重力作用下从底部开口穿过闸板进入下游 receiver。参数 `q` 只改变开口顶高 `0.10 + 0.16q m`；候选没有堰顶越流、旋转杯、预设壁面运动、悬空障碍物或 F3 impulse source。闸板上部实体和底部开口组成新的连续体拓扑，不能由 receiver/weir 的 full-height box 输入解释。

当前只交付 root-review-only contract。没有生成新的 Definition、GenCase/native BI4、trajectory 或 job；CPU/native preflight 仍为 `not_run`。15 行设计为 13 个空间行（q=`0/.5/1` × dp=`.01/.0075/.005` 加 q=`.25/.75` held-out）与 2 个 temporal comparator，全部 `not_started`，failure denominator 为 `15 planned / 0 executed / 0 credit`。

## 产物与 SHA-256

| 产物 | SHA-256 |
|---|---|
| [candidate-card-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/candidate-card-v1.json) | `0726648a24db7b0889870b7c35f852503dca42288cf88cd780408eb1167fac1d` |
| [fixed-matrix-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/fixed-matrix-v1.json) | `d3a275b6e6dc130bdf249f6d01a69d54c7f651831dd6a6ea289f70fd18c916eb` |
| [failure-denominator-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/failure-denominator-v1.json) | `cc34093a811db4a23edab3cf6e8dfc7ec5c01bb391eabe38b539ac55fb2edbc3` |
| [lineage-clarification-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/lineage-clarification-v1.json) | `42dbbe2181096855175110f74de6a997f37d3c5e23c7dcbb75be8d3406dd0e69` |
| [root-review-contract-v1.json](../campaigns/core-v1/cfd/f2-submerged-orifice-transfer-scope-v1/root-review-contract-v1.json) | `285f3bd5eef0e71ffe277afc73954627bc64694cf78879c9bb0df39694cc34f6` |
| [f2_submerged_orifice_scope_v1.py](../scripts/f2_submerged_orifice_scope_v1.py) | `8b697c3e2a8f23cfe1b0a36b0d699e060f6d876027057621becb3160b1343cb9` |
| [test_f2_submerged_orifice_scope_v1.py](../tests/test_f2_submerged_orifice_scope_v1.py) | `4ab3040ad08afc1cd092b3305a240a080952a3c797a85f6cd8151d022e43511a` |

The contract also binds four prior lineage references by SHA: receiver/weir negative evidence `844bb4c6e41b1000205b875d8efd540dd8c0438131c74f1b2324168cdb53d608`, F1 G1 negative evidence `d9bd24ead4064b1e4f87aa8194be668370b0a3648835309791399ae3194a37e2`, F2 DBC-duration negative evidence `0bba913c75b2a716b0756154239e11595feb753b428e2b4745563c5da3ff841d`, and the F3 baffle candidate lineage `4a0d6e07cc198e68f448ba33ba1f85c872d8ef7797746a47e9475724d2e2df33`.

## Verification and gate impact

`./.venv/bin/python -m pytest -q tests/test_f2_submerged_orifice_scope_v1.py` passed **4 tests**. `py_compile` and the standalone `verify` command passed. The tests cover the 15-row denominator, all-not-started state, candidate/contract hash closure, no old input reuse, q-dependent aperture geometry, novelty fields, tamper rejection, and closed runtime controls.

The Core gate is unchanged: `new_t1_family=false`, `qualification_credit=0`, `core_can_finalize_changed=false`. The next permitted action is a separate root review of this contract. If accepted, only one fresh q=`.5`, dp=`.0075` Definition/native anchor may be prepared on CPU, with its own source and generated-input hashes. No solver/GPU/queue/ledger/registry action is authorized by this artifact.
