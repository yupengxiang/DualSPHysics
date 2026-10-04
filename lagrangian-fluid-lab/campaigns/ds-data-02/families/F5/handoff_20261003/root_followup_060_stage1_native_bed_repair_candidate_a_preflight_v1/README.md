# F5 stage 1 candidate-A native bed preflight (060)

This fresh scope is source-only and disabled.  It records the bounded 057 native fixed-bed audit, selects one low-impact representation test, and provides disabled GenCase, initial typed-QA, and short-event solver templates for Root review.  It does not read H5/BI4 arrays, invoke GenCase, run a solver, convert output, or render.  Def050, Gen050, Root037, and the completed 057 report remain immutable.

## Evidence from completed 057

The report is summarized in `audit_057_bounded_summary.json`; the summary contains no native arrays.  Frames 0, 2, and 400 have the same 214515 particle axis, 168108 finite Type-0 rows, and 149532 finite mk40 rows.  The mk40 digest and XML cohort are stable: generated XML fixed range begin 5020, count 149532, and the native marker cohort matches it.  The x-evaluable cohort has nonzero counts in all six exact profile segments, with relative layers -32 through +43.  At the crest interval x=3.59..3.91, 221 mk40 rows occupy layer -32 at z=-0.19.  This supports a lower-closed, native-filled cohort.

The cohort is mixed boundary geometry: its y-width summary spans x=-0.25..4.83 and z=-0.19..0.85, while 3305 rows are outside the profile x domain.  The +/-0.01 mid-y strip is empty because the native y lattice does not contain zero.  These facts prevent an interior cross-section completeness claim.  They also provide no evidence for a thin or missing bed.  The prior Root037 fluid crossing remains in `root037_failure_ledger_summary.json` (21018/40710 below the bed by >0.02 m at frame 400; 19764/40710 by >0.04 m; deepest 0.5593415 m).  Its cause remains unassigned.

## Chosen bounded test

Candidate A (`candidate_a_patch.json`) removes only source lines 269--271: the duplicate `setmkbound mk=40`, `drawfilestl`, and `shapeout`.  The explicit 52-triangle profile mesh at lines 27--241 remains byte-for-byte, including the top nodes, y=+/-0.15 sides, and z=-0.15 lower closure.  Fluid clip/fill, motion, EOS, timestep, domain, and save settings remain unchanged.  Candidate B (the x=2..4.8, z=-0.15..0 underlay) is deferred: the audit already shows filled support through that region, so adding a second volume is redundant and may overlap existing bed/floor rows.  Candidate A is a representation-deduplication diagnostic, not a proven crossing repair.

## Disabled stages

- `gencase-request.json` uses the immutable source-preflight worker and the derived A definition, with a fresh output directory and a fail-closed baseline fluid count.
- `initial-qa-request.json` uses the standard F5 native typed QA template.  Root must bind a new GenCase receipt/prefix; the manifest's baseline counts are expectations, not results.
- `short-event-solver-request.json` is a disabled qualification template for a 0--1 s event-start diagnostic at the unchanged 0.02 s save cadence.  Root must bind fresh GenCase and QA receipts before any launch.  A short event cannot certify the late 8 s crossing absent, and full 16 s production remains unauthorized.

The requests use only supported runtime kinds (`cpu` with `gencase`/`audit`, and disabled `qualification` for the GPU solver template).  No Gemini model, numerical result, visual approval, Q-N, or production approval is claimed.
