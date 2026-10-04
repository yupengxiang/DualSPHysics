# F5 stage 1 candidate-A native bed strict chain (061)

This fresh scope is source-only and disabled.  It supersedes the 060 template only because 060 reused the old physical-case label and did not bind an explicit condition.  It records the bounded 057 native fixed-bed audit, selects one low-impact representation test, and provides disabled genuine-GenCase, actual-initial-QA, and short-event solver requests for Root review.  It does not read H5/BI4/CSV arrays, invoke GenCase, run a solver, convert output, or render frames.  Def050, Gen050, Root037, and the completed 057 report remain immutable.

## Evidence from completed 057

The report is summarized in `audit_057_bounded_summary.json`; the summary contains no native arrays.  Frames 0, 2, and 400 have the same 214515 particle axis, 168108 finite Type-0 rows, and 149532 finite mk40 rows.  The mk40 digest and XML cohort are stable: generated XML fixed range begin 5020, count 149532, and the native marker cohort matches it.  The x-evaluable cohort has nonzero counts in all six exact profile segments (60,223; 29,287; 18,477; 9,255; 15,845; 13,140), with relative layers -32 through +43.  At the crest interval x=3.59..3.91, 221 mk40 rows occupy layer -32 at z=-0.19.  This supports a lower-closed, native-filled cohort.

The cohort is mixed boundary geometry: its y-width summary spans x=-0.25..4.83 and z=-0.19..0.85, while 3305 rows are outside the profile x domain.  The +/-0.01 mid-y strip is empty because the native y lattice does not contain zero; that is a sampling limitation, not evidence of a hollow STL.  These facts prevent an interior cross-section completeness claim.  They also provide no evidence for a thin or missing bed.  The prior Root037 fluid crossing remains in `root037_failure_ledger_summary.json` (21018/40710 below the bed by >0.02 m at frame 400; 19764/40710 by >0.04 m; deepest 0.5593415 m).  Its cause remains unassigned.

## Chosen bounded test

Candidate A (`candidate_a_patch.json`) removes only source lines 269--271: the duplicate `setmkbound mk=40`, `drawfilestl`, and `shapeout`.  The explicit 52-triangle profile mesh at lines 27--241 remains byte-for-byte, including the top nodes, y=+/-0.15 sides, and z=-0.15 lower closure.  Fluid clip/fill, motion, EOS, timestep, domain, and save settings remain unchanged.  Candidate B (the x=2..4.8, z=-0.15..0 underlay) is excluded from this strict chain: the audit already shows filled support through every x segment and a 149532-row mk40 cohort, so adding a second volume has no evidence and may overlap existing bed/floor rows.  Candidate A is a representation-deduplication repair candidate, not a proven crossing repair.

The new physical binding is `physical_case_id=F5_COMPACT_STILL_WATER_RUNUP_REPAIR_A_V1` with `condition_id=F5_RUNUP_DP020_EQUILIBRIUM_ROOT050_A_EXPLICIT_CLOSED_MESH`.  It is a new condition record for this source recipe while `independent_case_count_increment=0` and the original physical mother remains identified.  The condition hash, source hash, audit hash, and all request hashes are bound in `physical-binding.json` and `strict-source-chain.json`.

## Disabled stages

- `gencase-request.json` is a disabled strict CPU request for one genuine official GenCase run into a fresh output directory.  Root must bind its actual completed receipt and generated prefix; no fictional or copied BI4 is accepted.
- `initial-qa-request.json` is a disabled strict CPU audit request.  Root must bind the new GenCase receipt and run the typed source/initial QA against the fresh XML/BI4; the Gen050 counts are fail-closed baseline expectations, not results.
- `short-event-solver-request.json` is a disabled qualification template for a 0--1 s event-start diagnostic at the unchanged 0.02 s save cadence.  Root must bind the fresh genuine GenCase receipt, fresh actual QA report, and the new condition before enabling it.  A short event cannot certify the late 8 s crossing absent, and full 16 s production remains unauthorized.

The requests use only supported runtime kinds (`cpu` with `gencase`/`audit`, and disabled `qualification` for the GPU solver template) and the integration worktree's `ds_data02_strict_dispatch_v1.py` guard.  No solver is started by this scope.  No Gemini model, numerical result, visual approval, Q-N, or production approval is claimed.
