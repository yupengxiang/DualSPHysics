# F5 fresh098: disabled full801 particle-level bed audit

fresh098 prepares the post-conversion, particle-level bed audit for the actual
C082S1 full event. It reuses the fresh096 profile and diagnostic semantics:

- exact piecewise bed profile x domain `[-0.2, 4.8]` m and y footprint
  `[-0.22, 0.22]` m;
- native bed `Mk50` with source `mkbound40`;
- finite Type-3 fluid rows only for the penetration footprint, while retaining
  all frame-zero fluid UIDs as the denominator;
- per-frame missing/unexpected UID, nonfinite, outside-footprint and
  unexplained-state reporting;
- diagnostic 1DP/2DP bins at 0.02 m and 0.04 m, with counts, fractions,
  deepest depth and samples; and
- no threshold relaxation, masking, resampling, mass rescaling, or inferred
  repair success.

The time contract is the actual full native event: 801 saved states from 0 to
16 s at the producer's 0.02 s cadence. The audit attempt is
`root-stage1-f5-c082s1-full801-native-bed-audit-353`, dependent on the future
XMF351 metadata and typed350 conversion. The source097 typed/XMF requests are
registered as disabled templates. Future trajectory H5, typed receipt/report,
full saved-state metadata, XMF manifest and XDMF paths/hashes remain explicit
Root-bind placeholders.

Root349 native metadata is real `completed/0` and is included as a JSON input;
fresh098 does not read its BI4 output or any future H5/XMF/CSV/VTK data. The
short 51-frame result is provenance only and is never reused as a full-event
pass. Full801 audit output remains diagnostic and requires Root review of every
frame and the full visual product before any case acceptance or case-count
change.

The request has `kind=cpu`, `cpu_task_kind=audit`, full input/hash closure,
`execution_allowed=false`, `launch=false`, `launch_allowed=false`, and
`full801_authorized=false`. The builder and preflight are metadata/AST-only;
no worker, solver, converter, ledger, registry or shared state is started or
modified by this package.
