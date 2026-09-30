# F2 evidence-bound scope validator

`lagrangian-fluid-lab/scripts/ds_data02_scope.py` is a dataset-only admission
check. It answers one question: does a frozen F2 scope have complete,
hash-bound evidence that is eligible for the primary process's separate
scientific decision? It does not write `approved_index.json`, mark a recipe
qualified, run a solver, or replace the numerical Q-N review.

The validator accepts two JSON documents:

* `ds-data-02.scope-spec.v1` freezes the recipe/schema, physical cases and
  parent/split assignments, geometry/control and numerical input bindings,
  complete event time, observation units and definitions, physical scales,
  error budget, the two backgrounds and three resolution views, and the
  required integration/save comparisons.
* `ds-data-02.scope-evidence.v1` supplies current full typed-state Q-I rows,
  six actual reference views, and independent integration/save comparison
  rows. Every `path`/`sha256` binding is rehashed from bytes when the verdict
  is produced.

The scope document must identify every case with `case_id`,
`physical_case_id`, `parent_group_id`, `split`, `physical_condition_hash`,
`geometry_family_id`, `control_family_id`, nonempty continuous `geometry`,
`control`, and `parameter_values`. Each resolution view carries frozen numeric
settings and a numerical recipe hash. A parent group may appear in only one
split. Resolution views remain views of that physical case; they never create
additional physical cases. For a production F2 scope, the scope's own case
registry and split artifact should state the intended 48 physical cases,
24 paired parents, and 24/6/6/6/6 split counts; this validator checks the
declared case identities, parent/split consistency, and view bindings.

The reference matrix is exactly two backgrounds (`center_catch` and
`offset_spill`) by three resolutions. Every reference row must bind the frozen
physical case and recipe, a completed 3-D solver with nonzero fluid, finite
boundary and motion coverage, the complete event window, and source roles
`geometry_xml`, `gencase_bi4`, `copied_motion`, and `solver_log`. The Q-I row
must bind a complete increasing timeline, positive fluid count and mass,
typed datasets (`time`, `position`, `velocity`, `density`, `mass`, `type`,
`valid`, `particle_id`, `particle_zone`, `rigid_body_state`), zero introduced,
revived, or type-changed identities, and saved moving-boundary pose/control
evidence. Boundary mass, physical spill, and numerical unknown mass stay
separate. Numerical exclusions remain evidence for the Q-I ledger and do not
grant Q-N.

The scope must require both an independent integration-step comparison and an
independent save-cadence comparison for each reference background. Each row
binds distinct baseline/comparison numerical recipe hashes, the frozen
baseline resolution, changed numeric fields, actual statistics, and both
`endpoint` and `internal` observations with nonempty metrics over the full
event window. An empty row, a label-only status, or a returned zero from an
unbound process is insufficient.

Old results can be listed under `evidence.reuse` only with all of the
following fields: `strict_scope_equivalence: true`,
`source_state_coverage: full_typed_state`, the exact current `scope_id` and
`scope_sha256`, the frozen recipe and time domain, every frozen physical case
ID, and at least one hash-bound equivalence report. A fluid-only H5 or a
qualified label is rejected. `qualified: true` and `production_eligible: true`
are rejected anywhere in active scope/evidence content. Q-E, other-family
evidence, material tracers, and model/prediction fields are ignored and cannot
rescue or block the dataset-only verdict.

Run the validator after the live evidence sidecars and source copies are
immutable:

```bash
lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/scripts/ds_data02_scope.py \
  --scope /path/to/F2-scope.json \
  --evidence /path/to/F2-scope-evidence.json \
  --data-root /home/jade/Projects/DualSPHysics-data/ds-data-02 \
  --output /path/to/F2-scope-verdict.json
```

Exit code `0` means `evidence_bound_eligible`; exit code `1` means the input
was read but is ineligible; exit code `2` means the JSON input itself could
not be read. The verdict records scope/evidence/validator hashes, every
rehashed artifact, structured failure codes, and
`approval_index_write: not_performed`. The primary process should accept a
verdict only when this exact verdict hash and its scope/evidence hashes are
inserted into the single root-owned approved index. The validator itself must
never perform that write.

The current tests use synthetic, hash-correct structural fixtures only. They
exercise a positive evidence-bound result, ignored optional domains, strict
reuse, source-byte tampering, missing reference/internal evidence, split
leakage, self-declared qualification, fluid-only reuse, and caller digest
mismatch. They do not claim that a scientific F2 result has passed Q-N.
