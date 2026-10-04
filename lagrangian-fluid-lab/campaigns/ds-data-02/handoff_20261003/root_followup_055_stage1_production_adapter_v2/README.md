# Stage 1 production authorizer v2

This is a source-only v2 adapter for the frozen F3 first8 visual domain.  It
leaves the consumed strict dispatcher, runtime, old production source, and the
052/054 handoffs untouched.  It performs no GenCase, solver, converter, or
ParaView work and does not write an approval index.

The v2 authorizer separates two Root records.  An individual
`ds02.stage1.root-visual-case-decision.v1` is required only for an observed
case that already has a complete visual record.  A prospective launch uses an
actual current-goal `ds02.stage1.root-visual-domain-decision.v1` with explicit
`observed_case_ids`, `prospective_case_ids`, and `selected_case_ids`.  The
prospective case may therefore launch with frozen physics/QA/input evidence
while its solver, typed conversion, original saved frames, and case visual
decision remain post-run evidence.  The v2 path never treats an interval as
permission to interpolate an unlisted case.

The actual Root domain record is bound in
`F3_INTERIOR012_PRODUCTION_REQUEST_RECIPE.v1.json`:

```text
root_stage1_f3_first8_observed_domain_decision_042/root-visual-domain-decision.json
sha256 7f33f48ddd33446a9f6684c673764727f1f01c1f6390b8d409facb9a91daea1e
```

The recipe remains `input_recipe_only` and `launch_allowed: false`.  Root must
construct a concrete v2 scope index entry and each request must still bind the
unchanged runtime/strict sources, exact command/cwd/window, frozen physics and
mass evidence, and genuine-parent/exact-clone QA.  The recipe lists the five
strict012 case identities, SI amplitude values, input hashes, and the future
visual-review contract.  It does not claim a per-case visual acceptance.
`F3_FIRST8_V2_SCOPE_ENTRY.template.json` is the matching pending index-entry
shape: it binds the three observed records and lists the five prospective IDs
explicitly, while retaining `execution_allowed: false` until Root performs its
adapter-index review.

The QA validator has two explicit branches:

* `genuine_3d_generation` requires an actual successful GenCase receipt,
  actual 3D counts, generated initial bytes, and passed initial QA.
* `exact_initial_clone_of_genuine_3d` requires the original genuine parent
  receipt and initial QA, a successful clone-preparation receipt, and byte
  equality for generated XML and BI4.  It never accepts a clone-preparation
  receipt as a new GenCase receipt and requires zero independent count
  increment.

Visual records are interpreted as JSON.  Their Root decision identity and
visual-only flags are checked, and the integrity report must state all 836
frames rendered, exact saved times, native identity, zero missing states and
zero nonfinite active states.  Decision observations such as unknown loss are
preserved as evidence and are not converted into a numerical precision gate.
The AY.50 mother keeps its original case and physical IDs and is counted once.

Run the source-only tests with:

```text
python3 -m pytest -q lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_followup_055_stage1_production_adapter_v2/test_stage1_production_adapter_v2.py
```

`ds_data02_stage1_dispatch_v2.py` aliases the v2 authorizer only for an
explicit `kind=production`, `visual_stage_profile=stage1_visual` request, then
restores the legacy import module.  It calls the consumed strict dispatcher
unchanged and writes a separate v2 semantic sidecar; the legacy execution
receipt bytes remain untouched.
