# F5 第三个 T1 候选路线关闭审计（2026-09-21）

结论：`F5_prescribed_wave_runup_x_v1` 当前关闭，审计范围内没有一个证据支持且物理机制真正独立的新假设。`qualification_claim=none`、`qualified=false`、`T1_numerical=false`、`matrix_credit=0`；本次审计没有写新 Definition，也没有运行 CPU/GenCase/native preflight。

proposal 给出的 H1 由 v3 具体测试：在不改变斜坡、块体、活塞、`q=0.5`、`dp=0.0075 m`、域边界和输出 cadence 的条件下，先用 `setmkvoid`/`autofill` 建立闭体排除，再重画物理 STL。v3 的 GenCase 和 native decode 成功，但 frame 0 的 fluid-only 几何硬门仍发现 1 个块体内部 endpoint（`fluid_first_id=94622`），所以 H1 失败。

v4 使用另一种官方 materialization：每个 watertight STL 只做一次 `setmkbound` 后的 `drawfilestl autofill=true`。它仍保持同一物理几何和输入参数，且同样得到 1 个 frame-0 fluid block endpoint（`fluid_first_id=94622`）。因此 v3/v4 是两种离散几何物化修复，不能被解释为新的波浪、接触、边界拓扑或观测物理机制；两者的共同科学失败保留在 authoritative failure summary 中。

proposal 的 H2 只提出 source-STL 与离散 MkCells 之间的接触带分类诊断。它明确不能放宽 exact fluid endpoint 或 saved-chord 硬门，也没有提供可通过该硬门的新物理机制。已有 v2 anchor 的只读抽样也记录了 `3354` 个 entity-penetration particle frames 和 `1435` 个 saved-chord crossings；这些 negative evidence 不被删除、不重解释为资格结果。

本次 receipt 只冻结谱系和关闭动作：

- v3/v4 的科学失败保留；同一输入不重试，旧 v2 Definition/XML/BI4/trajectory/output stem 不复用。
- solver、GPU、queue、job、registry、ledger、T1/T2 分母和 matrix 均没有 mutation；固定 15 行分母继续保留失败行，禁止 survivor renormalization。
- 只有在未来出现新的、可证伪且与现有两种 geometry materialization 机制独立的 F5 物理假设，并经过新的 root review 后，才可以重新开启路线。此 receipt 本身不授权任何 preflight 或 runtime。

证据 hash contract：

- `proposal`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/geometry-repair-proposal-audit-v1.json`，SHA-256 `3163d6e1d75b3ffacbda61afeb18e9e35a98e5e575ded254c6b7b86733ebee42`。
- `failure_summary`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/failure-summary-v1.json`，SHA-256 `d18299fd1335b9c65a33839256adbf26f165dfb61fe8636aaf9712ccc9282336`。
- `v3_root_review`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/root-review-receipt-v1.json`，SHA-256 `24b1bf0780dc905a7e17e31aeac7be1a2e98b5b0f9bd49eccefcff6e4e6b9dc1`。
- `v3_contract`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/input/geometry-repair-contract-v1.json`，SHA-256 `479df60b5bd610f6275e0343c0b5302a0fb5743da6074823bd29808c2c7e584b`。
- `v3_preflight`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/preflight-v3/preflight.json`，SHA-256 `eb91770a8a52b1495438d2ff9fe13d265d05053cb15109f3251a9da6ace25441`。
- `v4_root_review`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/autofill-bound-root-review-v1.json`，SHA-256 `c9f0a76ecee5876d42c0d49eda50f9cc4e55d371e9f44ffa1dd70b75d33ffb87`。
- `v4_contract`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/v4-input/geometry-autofill-bound-contract-v1.json`，SHA-256 `2910fac741812bc255b371da1592bca88fa0c6561a7cc3c337b73443ff6e06ce`。
- `v4_preflight`：`campaigns/core-v1/cfd/f5-wave-runup-third-t1/geometry-repair-audit-v1/preflight-v4/preflight.json`，SHA-256 `75f55fd80d01a067acb72e22888797b14e30ce22fc22d98ac90838c9ef519c2d`。
- `anchor_negative`：`campaigns/core-v1/evidence/f5-wave-runup-third-t1-anchor-negative-evidence-v1.json`，SHA-256 `d09cf0ca1388bb752909af61e520fb64b195766d3f8884968d587ff9a510b3d2`。
- `implementation`：`scripts/f5_wave_runup_route_closed_audit_v1.py`，SHA-256 `558e00eae798789b56073386e2519412859aaf643eb9fb33369057cd45e15887`。
- `test`：`tests/test_f5_wave_runup_route_closed_audit_v1.py`，SHA-256 `f7032db524c68e95fa11134e769de90b1e27bbc7445b6af6a39701a05a559613`。
