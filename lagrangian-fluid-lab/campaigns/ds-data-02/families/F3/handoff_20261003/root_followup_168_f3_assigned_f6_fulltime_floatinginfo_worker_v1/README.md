# fresh168: F6 full-time FloatingInfo delivery

This is an F3-owned, F6-targeted source package.  It supplies a disabled
Root142 CPU2 audit worker and 47 disabled per-case requests for the final F6
rows that currently have only a two-row state-zero FloatingInfo audit.  It
does not launch a job, grant visual/Q-N/Q-E credit, or change the shared
ledger, registry, native receipts, or existing scientific files.

The source coverage is the fresh167 final48 rigid-state report.  The baseline
full-time row is intentionally excluded; the package contains the other 47
physical cases, each with its own native receipt, `-dirdata` root, condition
roles, and `PartFloatInfo.ibi4` stat-only evidence.  The source evidence is
47 files of 180,376 bytes each (8,477,672 bytes total).  Those are file-size
observations only; no source agent opens or hashes the IBI4 files.

## Official input and semantics

The pinned DualSPHysics v5.4 help and binary are recorded in
`metadata/official-floatinginfo-contract.json`.  The documented `-dirdata`
input is `PartFloatInfo.ibi4`; the worker does not substitute a guessed
`FloatingMotion.fbi4` name.  The official command is bounded to
`-first:0 -last:240 -onlymk:60 -savemotion:1 -csvsep:0`, producing a complete
241-row `FloatingInfo_mk60.csv` export.  It retains the v5.4 roll/pitch/yaw
degree convention and the documented post-v5.0.204 pitch-sign note; it does
not convert Euler angles or infer marker values from a case alias.

`workers/run_fulltime_floatinginfo_fresh168.py` is fail-closed.  Root must
make an enabled copy with a private output directory, a completed,
hash-closed inventory report, 241 native producer times, and a pilot-bound
`part`-column contract before it can run.  The official header calls this
column `part` but does not document it as a frame index.  The source package
therefore leaves its marker-vs-frame mode and expected values null; a
registered pilot must bind either the observed constant marker or the exact
frame-index sequence.  The worker rejects any wrong or duplicated sequence
under that binding and never infers frame identity from the case alias.

The parser requires exactly 241 rows, strictly increasing time, start/end
coverage for 0..12 seconds with the declared tolerance, finite values, and the
complete unit-bearing groups: time, linear velocity, angular velocity, center,
translation pose, and Euler pose.  It compares official times with the 241
Root-bound native producer times using a finite, nonnegative `1e-6` second
tolerance, rejects any excess, retains both time vectors, and never resamples
or claims exact equality.

## Two-stage Root handoff

1. Enable a copy of `requests/partfloatinfo-inventory-disabled-request.json`
   through Root142.  `workers/run_partfloatinfo_inventory_fresh168.py` reads
   only the 47 explicitly listed `PartFloatInfo.ibi4` files, checks their
   before/after stat, and writes one completed inventory report containing
   their actual SHA-256 values.  The source request keeps its report and
   entry hashes null.
2. Use the Root-owned metadata preflight to bind 241 native producer times for
   each case and run one registered pilot to establish the official `part`
   semantics.  Freeze those facts, then bind the absolute inventory report
   path/SHA, matching per-case entry SHA, native-time vector, `1e-6` tolerance,
   and pilot part contract into an enabled copy of each request in
   `requests/f6-final48-fulltime-floatinginfo-disabled-request-index.json`.
   Set `disabled=false`, `source_only=false`, and `execution_allowed=true`
   only in the Root-owned copy.  Keep the native receipt and all canonical,
   source-plan, accepted-top, and legacy roles unchanged.
3. Run the enabled per-case copy through Root142 CPU2 with its own private
   output directory.  The worker first verifies the native completed/0
   receipt, the inventory binding, and the official v5.4 binary, then invokes
   the command above.  A completed report contains the produced CSV digest and
   parser evidence.  It does not hash H5/BI4 particle payloads.  Failed
   attempts retain a bounded report and do not become full-time evidence.

All source requests keep future receipt, report, CSV, and inventory output
hashes null.  `validate_fresh168.py` checks the disabled state, identity and
scope separation, exact official hashes, the stat-only 47-file inventory
contract, request closure, and absence of scientific payload files in this
package.  `tests/test_fulltime_floatinginfo_fresh168.py` uses only temporary
toy CSVs and covers a valid 241-row export, truncation, nonfinite values,
nonmonotonic time, and wrong units.

No output from this package is a visual decision or numerical qualification.
