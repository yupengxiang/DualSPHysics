# Production launch authorization

`ds_data02_runtime.py` supports qualification, bounded CPU work and production.
Both solver kinds use the same live GPU inventory, UUID lease, full GPU-time
reservation and protected foreign-process checks. Production uses its own
420-attempt cap and never increments accepted physical-case counts itself.

The primary agent owns `APPROVED_SCOPES.json`. It currently contains no approved
scopes. A request cannot replace this index or authorize itself with `qualified`.

Each approved entry binds a frozen scope spec, actual scope evidence, a root
scientific decision and a production manifest by SHA-256. The decision must
bind the same files; the scientific validator is run again using the dataset
venv. Missing, changed, spatially failing, incomplete or out-of-domain reference
evidence is rejected before a GPU lease. Q-E and other families are not gates.

The production manifest contains one entry per independent physical case.
Views cannot duplicate physical IDs or move parent groups across splits. Each
case binds its registered physical parameters, geometry/control, numerical
settings, full event window, exact solver argv/cwd, generated XML/BI4,
successful actual 3D GenCase receipt and actual initialization QA. The solver
prefix must match that receipt. Source hashes must match the GenCase launch.

Initialization QA is a separate `ds02.production-initialization-audit.v1`
artifact, including transverse layers, finite wall coverage, no initial fluid
and solid overlap, and continuous mass accounting without rescaling. Each
scope freezes `initialization_acceptance.relative_mass_error_max`, and each
physical case freezes `continuous_initial_fluid_mass_kg`. The launcher reads
actual generated `execution/constants/massfluid`, multiplies by the actual
fluid population and checks that mass against the frozen physical denominator.
Subtracting a dp-dependent missing support layer cannot change that denominator.

Only `physical_domain.evidence_case_ids` require prior complete trajectory Q-I:
these are reference/domain study cases, including every declared reference
mother. Prospective production cases need input QA and approved membership.
After solving, each production product must separately pass full-state Q-I,
labels, evaluation, preview, split and provenance acceptance. A zero return
code or an approved numerical scope is not final product acceptance.

The launch receipt records request-owner and runner-owner Git states separately,
as well as runtime/code/input hashes. Referenced inputs and the selected scope's
approval dependencies remain immutable while a launch runs. The selected
registry entry and the index hash at launch are copied into the receipt.
Adding another family's approval does not invalidate this case. The runner
rechecks the selected entry while running and at completion; changing,
duplicating or revoking that entry affects only its dependent cases. Version
approval manifests rather than patching completed evidence.
