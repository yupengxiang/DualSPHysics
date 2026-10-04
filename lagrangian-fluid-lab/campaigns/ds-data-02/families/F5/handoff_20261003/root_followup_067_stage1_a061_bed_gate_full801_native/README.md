# F5 A061 fresh067: actual bed-audit gate for disabled full801 native

This isolated F5 handoff prepares a metadata-only gate between the actual
51-frame short bed audit and a possible full 16-second native run. It does not
run GenCase, DualSPHysics, a converter, PartVTK, or any array reader. The
helper reads only JSON metadata and hashes files.

The previous full801 evidence is retained in
`root_followup_061_stage1_native_bed_repair_candidate_a_strict_v1/root037_failure_ledger_summary.json`.
The original diagnostic scanned 801 frames and showed below-bed occupancy in
the exact profile and `y∈[-0.15,0.15]` footprint: frame 400 had `21018/40710`
below 1DP and `19764/40710` below 2DP, with maximum reported depth
`0.5593415136933326 m`; frame 800 had `20491/40710` and `19199/40710`, with
maximum depth `0.5588833029866218 m`. That evidence withheld full16
authorization. The root cause remains unassigned and the old failure is not
rewritten.

The fresh gate requires an actual completed receipt and report from the
fresh066 bed worker. It checks all 51 frame records, the frame-zero Type-3 UID
reference, per-frame UID and finite/nonfinite fields, the exact seven profile
nodes, x domain and bed y footprint, 1DP/2DP counts and fractions, deepest
depth/sample fields, monotonic actual times, and the no-causal-claim policy.
It preserves the observed metrics as diagnostics. It never interprets a
penetration threshold as an acceptance threshold.

Before the actual bed audit exists, run only the source check:

```text
python3 scripts/bind_bed_gate_full801.py --check
```

After Root has a real completed bed-audit attempt, bind its metadata with:

```text
python3 scripts/bind_bed_gate_full801.py \
  --bed-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/<actual-bed-attempt>/execution-receipt.json \
  --bed-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_A061/<actual-bed-attempt>/a061-short-event-bed-footprint-audit.json \
  --output-dir /home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_067_stage1_a061_bed_gate_full801_native \
  --force
```

The helper writes `bed-gate-binding.json` and
`full801-native-request.json` only after both actual files exist. A malformed
or incomplete report produces a bound request with
`bound_status=blocked_bed_audit_validation`; a complete report produces
`ready_for_root_review_then_manual_enable`. Both states keep
`launch_allowed=false`, `full16_authorized=false`, `q_n_granted=false`, and
`independent_case_count_increment=0`. Root must manually review the complete
audit and enable the exact request before any full801 execution.

The full801 template reuses the genuine GenCase075 prepared prefix, actual
QA083 and native093 provenance, the unchanged Candidate A controls, and
`-tmax:16 -tout:0.02`. It preserves the source-plan hash
`268d4ea37228fb63ef493a6e535740bb765d165d874f97804443d5e11eb3497c` separately
from the typed065 canonical hash
`d4a165e67b16f4f4871aa8a37eaf7cef6c08796cbf644cf2c9e101af9f84fbb7`; the
difference does not authorize geometry or precision changes.
