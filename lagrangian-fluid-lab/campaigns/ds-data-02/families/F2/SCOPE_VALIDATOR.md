# Generic DS-DATA-02 evidence-bound scope validator

`lagrangian-fluid-lab/scripts/ds_data02_scope.py` is a dataset-only
eligibility check. The frozen scope supplies the family, mother/parent groups,
mechanism, geometry/control identities, state schema, and reference coverage;
the validator does not hard-code family mechanisms or require a second
mechanism in the same scope. A single explicitly declared background with
three resolution views can therefore be an independent starter scope. The
campaign-level seven-family and two-mechanism coverage requirement remains a
separate delivery condition.

The input documents are `ds-data-02.scope-spec.v1` and
`ds-data-02.scope-evidence.v1`. The scope must declare:

* `family_id`, `required_input_roles`, recipe/schema and solver dimension;
* `physical_domain.cases`, including `physical_case_id`, parent/mother group,
  split, mechanism, continuous geometry/control/parameters, physical hash,
  per-resolution numeric settings and numerical recipe hashes;
* `state_requirements.dataset_specs`, with actual H5 paths, rank/shape and
  units, plus identity fields, native fluid type values and conditional
  moving-body state. Static scopes can set `moving_boundary.mode` to
  `not_applicable`; scopes whose actual native `type` contains a declared
  moving value must declare the corresponding body-state dataset;
* `physical_parameter_domains`, with units and finite min/max bounds;
* `reference_requirements`, exactly three resolution views and an explicit
  `coverage_mode`. The campaign registration default is two backgrounds by
  three resolutions, while `single_background_explicit` is valid for one;
  `full_family_default` or `declared_multi_background` covers multiple
  backgrounds. Required source roles are frozen by the scope;
* integration/save comparison requirements, each with physical parameter
  `endpoint` and strict interior `internal` points and frozen
  `required_error_metrics`.

Every artifact binding is SHA-256 checked from bytes at validation time. The
Q-I row must bind one full-state H5 and one actual Q-I report. The validator
opens the H5 and checks the declared dataset paths, ranks/shapes, time-axis
coverage, integer `type`/identity data, boolean or binary `valid` data,
nonzero native fluid population, identity axis, and dataset/root units. It
does not accept a `dataset_names` list or a row boolean as proof. The Q-I
report is also read and its actual conclusion/status and failed checks are
compared with the statuses frozen under `state_requirements.qi_report`; a
`status="pass"` label in the outer row is not sufficient. Reference rows
carry the same H5/Q-I evidence at their own resolution.

Integration/save rows must provide `actual_error_metrics`. Each required
metric is compared numerically with the frozen observation error budget;
`within_budget=true`, `actual_pass`, or another self-declared label cannot
hide an exceeded threshold. `physical_parameter_points` must identify the
declared parameter and numeric value: an endpoint equals the frozen min/max,
and an internal point lies strictly inside. A time or frame index by itself
cannot satisfy either point.

An old qualified scope may be reused only when `reuse` declares
`strict_scope_equivalence: true`, `source_state_coverage: full_typed_state`,
a hash-bound `equivalent_scope_binding`, and a hash-bound equivalence report.
The old scope is parsed and its semantic projection (family, recipe, time,
observations, state, parameter domains, cases, references, comparisons and
input roles) is compared with the current frozen scope. A fluid-only H5 is
rejected. Q-E, other-family evidence, tracers, models, and their optional
labels are outside this dataset-only gate.

Run after evidence is frozen:

```bash
lagrangian-fluid-lab/.venv/bin/python \
  lagrangian-fluid-lab/scripts/ds_data02_scope.py \
  --scope /path/to/scope.json \
  --evidence /path/to/scope-evidence.json \
  --data-root /home/jade/Projects/DualSPHysics-data/ds-data-02 \
  --output /path/to/scope-verdict.json
```

Exit code `0` means evidence-bound eligible; `1` means read successfully but
ineligible; `2` means invalid input. The verdict binds scope, evidence,
validator and every artifact hash, and always reports
`approval_index_write: not_performed`. Root alone may add an exact verdict to
the approved index. This module does not launch or hook a runtime job.

The tests use small synthetic H5/report fixtures for structural verification.
They cover H5 type tampering, missing physical parameter points, time-frame
substitution, failed numeric metrics hidden behind a pass label, static
other-family scopes, explicit single-background scopes, strict old-scope
reuse, optional-domain isolation, split leakage, source tampering and digest
binding. They make no scientific Q-N or production claim.
