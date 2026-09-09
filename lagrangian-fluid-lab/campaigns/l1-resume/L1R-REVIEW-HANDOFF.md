# L1-R reviewer handoff

## Executive status

This is the implementation-and-evidence handoff for the L1-R continuation.
The user adopted the attached plan as the work direction. The attached ZIP is
a planning/validation package, not an authorization or a cloud-review
decision. The historical ChatGPT conversation referenced by the user was not
readable in this local session, so this document makes no claim of cloud
reviewer sign-off; every result below is grounded in the attachment, the
repository, and local executed evidence.

The continuation is isolated on branch `codex/lagrangian-fluid-exploration`
from baseline commit `404c565c9b43e5470f1830e1e9b81843465c2c38`. The retained
`campaigns/l1-qualification/` evidence was read only.

## Completed work

| workstream | result | reviewer meaning |
|---|---|---|
| Q0 finite-wall re-audit | completed for 9 retained W1 space cases plus W2-A | endpoint geometry, explicit runtime-domain semantics, and saved-frame chord crossings are now separated; failures/unknowns remain evidence, not silently reclassified |
| Q1 official control | completed | untouched same-version official mDBC assets generated successfully; official 3-D DamBreak produced a complete 601-frame raw positive control |
| Q2 recipe bridge | completed diagnostic, `quality_failed` | complete official mDBC recipe ran in isolated L1 geometry, but finite bottom-wall penetration prevents promotion |

No training, broad grid, formal release, or CPU substitute for the complete
qualification grid was started.

## Q0 findings

The compact report is
[`q0/REVISED_AUDIT_SUMMARY.json`](q0/REVISED_AUDIT_SUMMARY.json), with the
human-readable summary in [`q0/Q0-AUDIT.md`](q0/Q0-AUDIT.md). The audit now
uses five finite closed faces (`bottom`, `left`, `right`, `front`, `back`), an
open top, and an explicit runtime-domain check that is absent unless a domain
is declared. Adjacent saved-frame crossings are reported as chord-locator
intervals, not exact continuous trajectory events.

The retained mass ledger reconciles the H10 W1 ladder to:

| resolution | initial fluid mass |
|---|---:|
| coarse (`dp=0.020`) | 58.75200279057026 kg |
| medium (`dp=0.014`) | 58.216702714562416 kg |
| fine (`dp=0.010`) | 54.285002578399144 kg |

The medium-to-fine change is 6.753560323470175% and is recorded as a
discretization confound. The retained results requiring attention are W1 h09
fine and h10 fine (finite front/back endpoint excursions), W1 h11 fine (finite
endpoint penetration plus a right-face saved-frame chord crossing), and W2-A
h11 fine (finite bottom excursions plus solver position exclusions). The top
opening was not treated as a wall.

## Q1 evidence

See [`q1/Q1-OFFICIAL.md`](q1/Q1-OFFICIAL.md) and
[`q1/Q1-OFFICIAL-RESULTS.json`](q1/Q1-OFFICIAL-RESULTS.json). All three
untouched v5.4 official mDBC examples passed GenCase preparation with zero
final zero normals. The official 3-D DamBreak raw control completed on
allowlisted GPU 4 in `2439.113745564129 s` (`0.6775315959900359 GPU h`),
producing 601 raw BI4 frames and `19,529,195,271` bytes of BI4 evidence. No
resource guard, timeout, or interruption occurred.

This is a control-plane positive result only: it validates the same-version
official asset/execution path, not L1 boundary quality.

## Q2 evidence

See [`q2/Q2-MDBC-BRIDGE.md`](q2/Q2-MDBC-BRIDGE.md) and
[`q2/Q2-MDBC-BRIDGE-RESULTS.json`](q2/Q2-MDBC-BRIDGE-RESULTS.json). The
isolated candidate uses five normal-source face drawboxes and the official
complete mDBC recipe. GenCase produced 60,060 fluid and 75,915 boundary
particles. The solver completed on allowlisted GPU 4 in
`131.25813223607838 s` (`0.03646059228779955 GPU h`), with 601 raw frames and
no resource guard. Streaming normalization produced 601 frames in HDF5 with
initial/final valid fluid mass both `60.060002852696925 kg`.

The production audit is `quality_failed`: finite bottom-face penetration starts
at frame 403 (`0.403014 s`), occurs in 198 frames, and reaches
`0.03200000151991844 kg` outside mass. There are no runtime-domain excursions,
no swept crossings, and no solver position exclusions. Equal mass retention
does not make the geometric result acceptable.

## Code and verification

The main implementation changes are:

- `scripts/finite_wall_audit.py`: finite physical-face/obstacle endpoint and
  saved-frame chord audit helpers;
- `scripts/r5_f1_solver_gate.py`: production audit integration and compact
  finite-wall/sweep evidence;
- `scripts/r6_n2_campaign.py`: missing-identity classification separated into
  finite-wall, explicit-runtime-domain, open-top, and solver-exclusion causes;
- `scripts/l1r_q0_resume_audit.py`, `scripts/l1r_q1_official.py`, and
  `scripts/l1r_q2_mdbc_bridge.py`: reproducible continuation inventory,
  read-only re-audit, official control, bridge preparation/run/normalization;
- `tests/`: synthetic finite-wall, production integration, classifier, and
  Q1/Q2 recipe-contract coverage.

The targeted suite is green: 21 tests passed. A full repository test run is
the final pre-push check for this handoff.

## Review requests and recommended next gate

1. Confirm that finite physical faces and the open top are the correct Q0
   semantics, and that saved-frame chord times are accepted as interval-valued
   diagnostics.
2. Confirm the Q0 mass ledger and the classification of W1 h11 fine/W2-A
   exclusions as solver-side evidence rather than proof of physical exit.
3. Decide whether one bounded Q2 repair is warranted. If so, keep the same
   isolated case and require a clean finite-wall audit before any release or
   training use. Do not launch the broad grid yet.
4. If the bounded F1 path is closed, apply the planned fallback gate rather
   than treating Q1/Q2 controls as a qualified L1 dataset.

## Evidence pointers

- Q0 compact manifest: `campaigns/l1-resume/q0/REVISED_AUDIT_SUMMARY.json`
- Q1 compact manifest: `campaigns/l1-resume/q1/Q1-OFFICIAL-RESULTS.json`
- Q2 compact manifest: `campaigns/l1-resume/q2/Q2-MDBC-BRIDGE-RESULTS.json`
- Q2 normalized HDF5: `campaigns/l1-resume/data/q2-mdbc-bridge/L1R_Q2_MDBC_BRIDGE_h11_fine_dp0p01_cfl005_t0p6.h5`
- Full Q2 audit artifact: `campaigns/l1-resume/artifacts/q2-mdbc-bridge/L1R_Q2_MDBC_BRIDGE_h11_fine_dp0p01_cfl005_t0p6-audit.json`
- Full raw outputs are ignored but retained locally under the Q1/Q2 `runs/`
  and `artifacts/` roots; compact manifests carry their attempt paths.
