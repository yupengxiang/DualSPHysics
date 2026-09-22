# F3 native-MLS acceptance bridge v2/source-closure reconciliation（2026-09-22）

结论：本 artifact 是只读、fail-closed 的 source-closure reconciliation；不授予 T2，`qualification_claim=none`，`credit=0`，`T2_macro=false`，`T2_path=false`。

本次只读取 JSON receipt 和源码文本/哈希；没有打开 HDF5，没有启动 solver、GPU、queue，没有生成 CFD，没有修改 registry、ledger、matrix 或 denominator，也没有覆盖历史 receipt。

artifact：`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f3-native-mls-acceptance-bridge-v2/reconciliation-v1-20260922.json`；namespace：`f3-native-mls-acceptance-bridge-v2/reconciliation-v1`。

## 统一结果

- trace/checkpoint schema binding：`True` / `True`；只表示 provenance，不表示 acceptance。
- per-source unknown：`False`，保留全分母和 right-censor，固定上限 `0.01`。
- first-passage/return/residence CDF：`False`，固定 sup 上限 `0.02`。
- dense cadence：`False`；声明 interval `0.01` s，而要求 `0.002` s。
- full event window/right-censor：`False` / `False`。
- 33-row formal receipts：`0`；matrix ready=`False`。

## rows 28/32、row 24 和缺失 source

- row 28：现有 profile source audit 存在，但仅提交 `21` 帧、结束于 `0.2000113023685942` s；不是 8.35 s formal source，CDF/residence receipt 缺失，credit=0。
- row 32：当前 evidence namespace 没有 exact source audit；source-available matrix status 不等于 source output，credit=0。
- row 24：完整 dense source 的 negative acceptance receipt 保留；first-passage/return CDF 失败，不能因 window complete 而转为正验收。
- dense cadence：保留 nominal `.01` 与要求 `.002` 的不一致，fail closed；不会用 observed median 取代错误的声明。
- missing exact sources：rows 16–23、26–27、29、31 仍按 gap audit 保持缺失，不以模板或其他 amplitude 替代。

## 当前 core_material.py hash closure

新 artifact 绑定当前 `scripts/core_material.py`；历史 gap audit 的旧 hash 仍只作为历史证据存在，没有篡改。后续任何正式 collector 必须重新验证本 artifact 的 input bindings。

## blocking reasons

1. retained per-source unknown maximum 0.015625 exceeds 0.01
2. retained first-passage/return/residence CDF maximum 0.06103515625 exceeds 0.02
3. row 24 is a negative scientific receipt: first-passage and return CDF gates fail despite complete window
4. dense source cadence provenance fails closed because retained nominal interval .01 disagrees with required .002
5. row 28 has only a short profile source audit; row 32 has no exact source audit
6. rows 16-23, 26-27, 29 and 31 remain missing exact root-owned CFD sources
7. all 33 matrix rows lack an independent formal acceptance receipt

## input hashes

- `core_material`：`scripts/core_material.py` — `431fe2a355037423e01629412315a7d5e73f3b259bee262e1384ebb33168cf3e`
- `core_material_acceptance`：`scripts/core_material_acceptance.py` — `b9cb49cacf19590356bda4f32d32ef3d2255b9c97a8afa29a920e5a38bd6c4a7`
- `native_mls`：`scripts/f3_native_volume_mls.py` — `e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9`
- `native_mls_compare`：`scripts/f3_native_volume_mls_compare.py` — `d4fc40b0b0057b4b0fc2487560d709f01c95068109a028e2664bc9f6fdf44acb`
- `native_mls_temporal_v3`：`scripts/f3_native_volume_mls_temporal_v3.py` — `30ea09d28bcf1edf2a4dfbab5ff314c593e26cc942ab125bbcacad854568d395`
- `gap_audit_v2`：`campaigns/core-v1/material/evidence/f3-t2-admission-acceptance-gap-audit-v2-20260922.json` — `90986f272225ac7faf08c75a1403dc19b140cd7351062ebe8aa133cb6bc1b5f0`
- `source_closure_audit_v1`：`campaigns/core-v1/material/evidence/f3-t2-source-closure-audit-v1-20260922.json` — `84332ab4fd6c17094ce52f7039978d9c1e5274d70a6c374ac258868d457394a3`
- `prior_bridge_v2`：`campaigns/core-v1/material/evidence/f3-native-mls-acceptance-bridge-v2-20260922.json` — `9826c1b543a861226b38e941b214bdd45f03a353bdf390f87f9b4778449160f3`
- `matrix_gap_audit`：`campaigns/core-v1/material/evidence/f3-native-mls-33-matrix-gap-audit-v1.json` — `b1cf2d4943d07e095343c664d8b704d4217ac920cd3672600da5a3e28af288a3`
- `row24_negative_receipt`：`campaigns/core-v1/material/evidence/f3-row24-native002-vs-matched010-negative-acceptance-receipt-20260922.json` — `47009460f0b7d28155fbc8a6291327f8c2c186c1cb6214f54b9da5e62d30fe17`
- `row24_comparison`：`campaigns/core-v1/material/evidence/f3-row24-native002-vs-matched010-comparison-20260922.json` — `a26091424c87ac393a7b4fc4d852308c28c738e3c0c91ba754ade94cca1b7482`
- `row28_profile_receipt`：`campaigns/core-v1/material/evidence/f3-t2-seed-density-s4-row28-profile20-receipt-v1.json` — `0c4e3483363fcb6060630e559684089123810f37b62e5f75a485ac6d0396d0bb`
- `row28_source_preflight`：`campaigns/core-v1/material/derived/f3-t2-seed-density-s4-row28-profile20-v1/source-preflight.json` — `7a3c2cad85e6bcea17742f16379d7759992b7f330ea0d94bf7bdb8b516182da5`
- `row28_trace_summary`：`campaigns/core-v1/material/derived/f3-t2-seed-density-s4-row28-profile20-v1/trace.summary.json` — `ae6821b6d63a5c665779ec4b935c6953380b49fb726ed4ec81dc546f08a77806`
- `row28_checkpoint_manifest`：`campaigns/core-v1/material/derived/f3-t2-seed-density-s4-row28-profile20-v1/trace.h5.checkpoint.json` — `febab5ea8c4474905b8cc7d653e6d13b26f1b9b1fa87d27da3978d005422b761`
- `dense_source_preflight`：`campaigns/core-v1/runtime/attempts/ada-f3-native-mls-dense-native002-production-s4-full835-v2/20260920T000456-ba294af97b9d/source-preflight.json` — `2891b764294a3a8c6ad1b1dadbf06e507ca936da3dc50a64f8d4d6deb58a124b`
- `bridge_implementation`：`scripts/f3_native_mls_acceptance_bridge_v2.py` — `76e4e48b33280e43e1e69e2318223fabc4c18fdfe538c7c85163d20acbbc71ab`
