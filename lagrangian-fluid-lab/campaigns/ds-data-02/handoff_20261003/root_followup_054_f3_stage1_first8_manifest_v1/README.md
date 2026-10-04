# F3 Stage 1 first8 candidate manifest

This handoff is a source-only candidate package for the first F3 Stage 1
visual domain.  It does not create `APPROVED_VISUAL_SCOPES.json`, grant a
production scope, claim Q-N/Q-E, or launch a job.

The proposed physical axis is exactly

```text
AY = .25, .32, .39, .46, .50, .57, .64, .75 m/s²
pitch multiplier = 1.0
dp = .006 m
window = [0, 8.35] s
saves = .01 s (836 expected states)
```

Geometry, event semantics, and the adaptive numerical recipe stay bound to
the F3 CELL3 plain finite tank.  The candidate carries explicit physical
condition hashes and source identities for all eight rows.  The AY.50 row is
the existing mother with `case_id`
`F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005` and
`physical_case_id` `F3_TWOAXIS_AY0P50_PITCH_NOMINAL`; it is retained by that
identity and is not recast or recounted as a Stage1 batch case.

The lower and upper endpoint decisions are the actual Root records from
`root_stage1_f3_endpoint_visual_acceptance_021`.  They bind full 836-frame
animation integrity reports and retain `production_scope_approval: false`,
`q_n: not_granted`, `q_e: not_assessed`, and the label
`视觉检查通过、数值精度未验收`.  The mother decision from anchor010 is carried
as immutable historical evidence because it was authored under the prior
goal; the active GPT56LUNA goal is bound separately.

The five strict012 rows are prepared exact initial inputs only.  Their XML
and BI4 hashes equal the genuine 3D DP006 parent, and their forcing files
carry distinct physical condition hashes.  They have no solver, typed,
ParaView, original saved-frame, or case-level Root visual decision in this
handoff.  The candidate therefore leaves the aggregate domain decision,
final visualization decision, and full-scope frame-integrity binding
explicitly pending.  A future Root domain decision may select only the
observed mother/endpoints and mark the five interiors prospective; it must
not imply review of unrun interiors or authorize interpolation.

Files in this scope:

* `F3_FIRST8_PHYSICAL_DOMAIN.v1.json` records the canonical physical keys,
  solver recipe, exact AY axis, and per-row condition identities.
* `F3_FIRST8_CASE_PROVENANCE.v1.json` binds the genuine parent, exact-clone
  provenance, endpoint records, source input hashes, and pending interior
  visual records.
* `F3_FIRST8_CANDIDATE_MANIFEST.template.json` is the frozen candidate index
  shape.  Its `execution_allowed` and production flags are disabled and its
  aggregate decision path is null by design.
* `ADAPTER_V2_REQUIREMENTS.json` is the concrete contract for a later Root
  adapter update: genuine-generation versus exact-clone QA, explicit
  aggregate-domain semantics, per-case decision validation, and full saved
  frame integrity checks.
* `source-audit.json` records the integration inputs, strict012 outputs,
  endpoint decisions, active goal, and preserved runtime/strict/old
  production hashes.
* `validate_candidate_manifest.py` verifies JSON structure, source hashes,
  endpoint decision metadata, and endpoint report metadata without opening
  raw arrays or launching a workload.

Run the source-only check from the infra worktree with:

```text
python3 lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_followup_054_f3_stage1_first8_manifest_v1/validate_candidate_manifest.py
```

Before any production request can be assembled, Root must supply an actual
current-goal `ds02.stage1.root-visual-domain-decision.v1` binding with an
explicit frozen membership, and the selected cases must have actual physics,
geometry, motion, no-overlap, mass-discrepancy, solver, QA, typed, and
original saved-frame evidence.  The unchanged runtime and source052 adapter
remain outside this handoff.
