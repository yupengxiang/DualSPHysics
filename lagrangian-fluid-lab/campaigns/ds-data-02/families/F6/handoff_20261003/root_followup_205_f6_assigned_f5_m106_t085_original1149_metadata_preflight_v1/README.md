# fresh205 — F5 M106/T085 original1149 metadata preflight

This isolated F6 handoff is a read-only metadata preflight for
`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M106_T085_NEXT34` / `F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085`. It records the real GenCase, initial-placement QA,
native, typed, bed, XMF and original1149 render-chain metadata. The original
1149 render was observed running at the initial preflight and then completed with returncode 0; the frozen terminal snapshot records (`controller PID
253004`, start ticks `210338104`, worker PID
`802577`); Root QI was completed once, but this package does not claim personal visual review or case credit. The terminal report and publish receipt are metadata-only; PNG review remains a separate fresh206 task.

The producer roles remain separate:

- canonical/native physical condition: `0c0013f50e2bca5bee381eadcf19a031f1a4463e550fffc02d41097f911f46bb`;
- typed converter legacy scope: `61d53c17e86f01264f08e92fa855f2d0056b9d834bb4509083267db1afb4ec83`;
- registered SourceDef XML: `6562d493dde651c415ad5eef9cf9aaae6fa7938ee21ab4e10f99ef398fa84fac`;
- source-plan JSON: `366adc5200604490871116a0a5b8503c9bef4bfb1e72195df94995605fa7d324`;
- native/XMF physical-plan scope: `0c0013f50e2bca5bee381eadcf19a031f1a4463e550fffc02d41097f911f46bb`.

The native request and XMF manifest have no `source_plan_condition_sha256` key; their physical-plan field is the canonical scope. The XMF manifest has no `source_plan_condition_sha256` key. The separate
`metadata/fresh204-xmf-scope-correction.json` records this fact for fresh204
without modifying fresh204's committed bytes; its original claim is retained
as history. No science payload, private PNG, or renderer output was read,
hashed, or copied by this package.

The render is now terminal completed/0 and atomically published; Root QI proof is recorded as a metadata reference. No PNG was opened or hashed here. Observed producer counts are 801 frames, 194427 particles, dimension 3,
fixed 158559, moving 4210, floating 0, fluid 31658. Typed producer time
metadata is 0.0 through 16.00014041930218 seconds and strictly increasing;
nominal 16.0 is not substituted. Initial placement QA and bed diagnostics
remain diagnostic evidence and do not grant visual, numerical, Q-N, Q-E, or
case credit.

Run the validator from this directory:

```text
python3 scripts/validate_fresh205.py
```

The validator checks only JSON/XML/Python metadata and the frozen local live
snapshots. It does not open or hash H5, BI4, DAT, CSV, VTK, PNG, or other
scientific payloads.
