# F5 fresh132: endpoint full801 visual review, pending

This source-only pack records the real endpoint status observed at `2026-10-06T04:23:24.278039+00:00` for the
current M115_T100 Root783 renderer and the new M085_T080 Root786 CPU-slot-repair
attempt. M115 is still `running` without a terminal receipt. M085 Root786 has no
receipt yet while its sequential controller is live. The old M085 Root783 receipt is a
shared CPU reservation prelaunch failure and is explicitly excluded from visual
acceptance.

No PNG was opened in this pending snapshot. No BI4, DAT, H5, CSV, VTK, or solver
payload was read, copied, or hashed by source preparation. There is no case credit and
no release of the ten fresh131 requests.

When either new endpoint has a receipt with `status=completed` and `returncode=0`,
Root may review that endpoint independently. The review must enumerate the actual
producer render directory, find all 34 contact images plus the actual key/original PNG
set, inspect every one with `view_image`, and record each actual PNG path and SHA256
in a new sidecar. A return code or a bed diagnostic alone cannot open the gate. The
remaining ten conditions stay disabled until both endpoint visual decisions are
explicitly accepted. Historical exact-DP 1e-6 and A/B penetration negatives remain
unchanged.

## Files

* `metadata/fresh132-endpoint-status.json`: immutable metadata-only status snapshot,
  including Root783/Root786 attempt paths and the excluded old failure.
* `metadata/fresh132-visual-review-plan.json`: review contract and WAIT gate.
* `scripts/validate_fresh132.py`: package-only validator; it never opens scientific
  payloads and does not start a task.
