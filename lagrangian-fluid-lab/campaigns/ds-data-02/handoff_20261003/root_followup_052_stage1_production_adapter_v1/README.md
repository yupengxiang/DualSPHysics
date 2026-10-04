# Stage 1 visual production adapter

This handoff is a source-only adapter and authorizer for the DS-DATA-02
visual-first production stage.  It contains no `APPROVED_VISUAL_SCOPES.json`
and grants no scope.  Root creates that file only after the actual visual
review and binds it to the active updated GOAL.

The canonical source files are:

* `ds_data02_stage1_production.py` — visual-only authorizer and request
  builder;
* `ds_data02_stage1_dispatch_v1.py` — explicit dispatch adapter and receipt
  sidecar writer; and
* `APPROVED_VISUAL_SCOPES.schema.json` — structural index contract.

`consumed-source-audit.json` records the observed SHA-256 values of the
integration worktree's three consumed source files.  It is an audit record,
not an approval index or a replacement source.

The root integration worktree installs both Python modules beside the
consumed `ds_data02_runtime_v2.py` and `ds_data02_strict_dispatch_v1.py`.
The consumed files remain byte-for-byte unchanged.  The adapter imports the
strict dispatcher and, for one request only, temporarily aliases the new
authorizer as `ds_data02_production`; it then calls the original
`strict.run_request`.  Requests without both `kind: "production"` and
`visual_stage_profile: "stage1_visual"` are rejected before the alias is
installed.  The old dispatcher remains the path for every ordinary request.

## Index and evidence contract

The root-owned index has schema `ds02.root-approved-visual-scopes.v1`,
campaign `DS-DATA-02`, an exact `goal_authority` path/SHA-256 binding, and a
list of scope entries.  Each entry includes a Stage 1 profile, a root visual
decision, full visual evidence with non-empty `mother`, `endpoints`, and
`interior` bindings, a final visualization decision binding, a complete
saved-frame integrity binding, a frozen physical domain, and a frozen case
manifest.

The visual decision must say `visual-approved-by-root`, retain the label
`视觉检查通过、数值精度未验收`, set `production_scope_approval` to `false`,
and leave `q_n` and `q_e` ungranted/unassessed.  The authorizer never invokes
the legacy scientific scope verifier and never treats spatial convergence,
time-step error, save-frequency error, macro comparisons, or external
validation as hidden launch gates.

Each manifest/domain case has a unique `case_id`, unique `physical_case_id`,
and unique structured `parameter_tuple`.  The tuple cannot contain DP, time,
frame, resolution, save, or alias keys.  The request must equal the frozen
physical tuple, physics/geometry/motion, actual solver argv, actual cwd,
numerical recipe, and complete event window.  Case evidence must bind actual
3D GenCase output and positive counts, the genuine generated initial bytes,
equivalent-clone initial-state QA, physics/geometry/motion finite-state
evidence, no-initial-overlap evidence, and the initial mass discrepancy
report.  The report is carried forward as evidence; mass rescaling is
rejected, while no arbitrary precision budget or tolerance is evaluated.

Source hashes for the new adapter, new authorizer, consumed strict
dispatcher, and consumed runtime are mandatory `input_files` and registered
`input_sha256`/`input_hashes` entries.  The mutable visual index is excluded
from this immutable input map and is captured in the launch context instead.

## Lifecycle and receipt semantics

`authorize(request, index_path=..., approval_context=...)` performs all
source/evidence and frozen-membership checks before a lease can be acquired.
It returns the immutable hash map consumed by the unchanged runtime and
records the selected entry digest in `approval_context`.

`revalidate_approval(context)` checks only the selected family/scope entry and
the active GOAL binding.  Adding an unrelated family entry is allowed; a
selected-entry edit/removal/duplicate or GOAL change raises and the unchanged
runtime stops the selected process on its next revalidation check.

`run_request(path, **kwargs)` validates the explicit profile, installs the
temporary alias, calls the original strict dispatcher, restores the alias in
all cases, and writes
`execution-receipt.visual-stage1-semantics.json` beside a returned runtime
receipt.  The original receipt bytes are never rewritten.  The sidecar states
that the legacy top-level `numerical_reference_status:
"approved_scope_at_launch"` means visual launch binding for this
`stage1_visual` profile only; numerical precision remains not accepted and
final acceptance is separate.

The `build_request(...)` API only copies frozen metadata and hashes input
files.  It does not call GenCase, a solver, a converter, ParaView, or any
other numerical process.  The included tests use temporary JSON/binary files
and fake strict/runtime modules; they exercise authorization tampering and
alias lifecycle without launching a job.
