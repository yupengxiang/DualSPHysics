# ROOT257 generic native extraction handoff

This is a source-only handoff for the already prepared ROOT257 request. It is
not an execution receipt and gives no scientific or historical-118 credit.
The parent guard must bind the request, manifest, worker, official tool, and
terminal inputs by the exact paths and SHA-256 values below before execution.

## Frozen request and command

- Request: `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/generic-native-extract-v1-root-forward-257-004.json`
- Request SHA-256: `c76abc7baf3c0cae9980f92e565c64b1bc0f077bb0050f489f456326f2d50330`
- Manifest: `/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/generic-native-extract-v1-root257-f4-prepared-004/generic-native-extract-manifest.json`
- Manifest SHA-256: `ab8d48c7b62aab5c68f888ba4881e36d2d02b657614d61c7e289409a2ad6d48b`
- Generic builder SHA-256: `296236fbbcae89e9537a4b93bb406ef3ee435dff661927fe976c3f054cea3a74`
- Intake V1 SHA-256: `bc76d2ac98a1749d84395aa8b24a4823a3ef7c9d27c5102cd2c33f02b27a18ad`
- Intake V2 SHA-256: `9df7639021585463fa8c366cbaa9a0201fcc1ce62e6ce76e86477c588738fd19`
- Official `PartVTKOut_linux64` SHA-256: `62630430902484f4aede017108313673fe6414f40fb59b6ae7f14ac23219db00`
- Official `DsphConfig.xml` SHA-256: `a2bc1f88c6ea95347187a64a991ebada177c6314de5c35ab078b06d78235eece`

The request's literal command is:

```text
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python /home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_build_generic_native_extract_v1.py audit --manifest /home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/generic-native-extract-v1-root257-f4-prepared-004/generic-native-extract-manifest.json --output {attempt_root}/generic-native-extract.json
```

The request is one CPU thread, one case at a time, 3600 seconds, 4 GiB,
estimated deferred read `34359745221` bytes, and estimated output/storage
`8388608` bytes. The deferred OBI4 pass is parent-reserved; no solver starts.

## Exact case scope

The request has eight exact case IDs. Three are historical-118 members and
five are diagnostics only:

| case ID | scope |
|---|---|
| `F4_DROP_B08_gap0p20000_xoff0p00000_yoff0p00000_uz0p50000` | diagnostic only |
| `F4_DROP_B08_gap0p21000_xoff0p00000_yoff0p00000_uz0p50000` | diagnostic only |
| `F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p40000` | historical-118 exact |
| `F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p60000` | diagnostic only |
| `F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p40000` | historical-118 exact |
| `F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p60000` | diagnostic only |
| `F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p40000` | diagnostic only |
| `F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p60000` | historical-118 exact |

The exact eight-case set comes from `request.physical_case_ids` and
`request.case_scope`; the manifest is authoritative. The diagnostic-only five
are:

1. `F4_DROP_B08_gap0p20000_xoff0p00000_yoff0p00000_uz0p50000`
2. `F4_DROP_B08_gap0p21000_xoff0p00000_yoff0p00000_uz0p50000`
3. `F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p60000`
4. `F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p60000`
5. `F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p40000`

The three historical-118 exact cases are:

1. `F4_DROP_gap0p24000_xoff0p08000_yoffm0p04000_uz0p40000`
2. `F4_DROP_gap0p22000_xoff0p08000_yoffm0p04000_uz0p40000`
3. `F4_DROP_gap0p22000_xoffm0p08000_yoff0p04000_uz0p60000`

The historical membership source is
`HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json`, SHA-256
`3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00`.

## Report contract and credit rule

The worker report schema is `ds02.stage2.generic-native-extract-report.v1`.
Each case result has `status`, `physical_case_id`, `historical_118_membership`,
`counts.typed_targets`, `counts.native_rows`, `counts.joined`, exact
`(Zone, Idp)` rows, and saved-bracket evidence. The batch status is either
`COMPLETED_ALL_CASES` or `COMPLETED_WITH_CASE_FAILURES`.

For a diagnostic-only case, a result with zero typed targets, zero native rows,
and zero joins must be retained as an explicit diagnostic/no-target outcome
(operational label: `NO_TARGETS_OR_DIAGNOSTIC_ONLY`). It is not a failed
worker and it gives zero historical-118 credit. A nonzero diagnostic result
remains `DIAGNOSTIC_ONLY` and also gives zero historical-118 credit.

Only the three exact historical-118 cases can receive a new cause/join credit,
and only when their case identity, source membership, complete `(Zone, Idp)`
join, saved brackets, and terminal receipt all validate. A failed case, an
empty target set for a historical case, a global count, an empty PartOut, or a
cross-case substitution gives zero credit. Physical fate, legal flux,
continuous event time, dynamics, QI, QN, and QE remain `UNKNOWN`.

The current generic V1 report has a diagnostic-only status and explicit zero
counts but does not emit a dedicated `NO_TARGETS_OR_DIAGNOSTIC_ONLY` enum.
That is a report interpretation rule for the parent verifier; the consumed V1
worker/request bytes remain unchanged. Do not convert the five diagnostic cases
into positive joins merely to make all eight cases nonempty.

## Execution boundary

ROOT257 was prepared only. Until the parent produces a fresh terminal receipt,
case reports, and an independently checked output SHA, the request is
`NOTRUN` and has no coverage credit. Any output path is therefore the template
`{attempt_root}/generic-native-extract.json`; it must not be replaced by an
arbitrary latest path.
