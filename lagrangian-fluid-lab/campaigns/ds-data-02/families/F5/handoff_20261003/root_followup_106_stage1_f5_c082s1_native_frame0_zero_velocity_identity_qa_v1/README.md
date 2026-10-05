# F5 fresh106: native frame-0 identity and zero-velocity QA

This is a source-only handoff for the two already completed Root455 short
native attempts:

* root-stage1-f5-c082s1-A080-short-native-qualification-104-root455
* root-stage1-f5-c082s1-A120-short-native-qualification-104-root455

The producer metadata is bound to the actual Gen426 prepared reports and the
actual Root455 receipts. Both candidates have the producer counts
194427 = 158559 fixed + 4210 moving + 0 floating + 31658 fluid, 3-D, and
51 requested saved states.

The two requests in requests/ are deliberately disabled
(kind=cpu, cpu_task_kind=audit, launch=false, execution_allowed=false).
A Root-registered CPU worker may be enabled only after review. It invokes the
official PartVTK executable on the actual solver-saved
solver_output/data/Part_0000.bi4, then independently checks:

* the frame-0 summary (t=0, Np=194427, Nfluid=31658);
* finite positions, mass and density;
* integral Zone/Idp/Type/Mk fields, zero Zone, consecutive unique Idp values,
  exact producer Type counts, and unique coordinates with non-overlap between
  Type partitions;
* genuine 3-D extent;
* the native Type-3 fluid count and its measured initial velocity against the
  source declaration [0, 0, 0] with tolerance 1e-8 m/s.

The worker never substitutes GenCase CSV velocity for the native saved state.
The source builder did not open or hash BI4, H5, CSV, VTK or motion DAT. Those
payloads remain Root-owned runtime inputs; the future worker report, receipt
and PartVTK CSV digests are null here.

The source marker mapping remains mkbound=40 to native bed Mk=50.
The historical exact-DP lattice threshold 1e-6 failure is retained as a
separate numerical negative and is neither loosened nor relabelled by this
identity QA. This package grants no Q-N, visual acceptance, full801/full16
approval or independent case count. Root must review the completed frame-0
report before enabling fresh105 typed conversion.

Validate metadata and disabled-request closure with:

    python3 scripts/validate_fresh106.py

No solver, PartVTK, converter, renderer, array reader, registry write or
ledger mutation was started during source preparation.
