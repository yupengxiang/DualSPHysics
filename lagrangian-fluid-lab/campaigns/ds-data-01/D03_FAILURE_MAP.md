# DS-DATA-01 D03 failure map

This map is a dataset-scope diagnostic. Q-I/Q-N checks do not constitute scientific acceptance.

| Code | Cases | Meaning |
|---|---:|---|
| `2D_CALIBRATION_ONLY` | 1 | 2D contrast is useful for calibration/control tests but is not a 3D production acceptance case |
| `CLOSED_IDENTITY_OR_MASS_INVARIANT_NOT_MET` | 1 | candidate does not satisfy the current closed-trajectory identity/mass invariant |
| `EXCLUSION_NEGATIVE_RETAINED_AS_NEGATIVE_CONTROL` | 1 | historical run is retained to document a known unsuitable scope, not as a positive dataset member |
| `MISSING_MASS_SCOPE_AUDIT_REQUIRED` | 7 | the derived rotating-pour report records numerically missing particles; retain as diagnostic until the lifecycle scope is explicit |
| `OPEN_LIFECYCLE_FLUX_AUDIT_REQUIRED` | 2 | particle population changes because an open boundary introduces or removes particles; a closed-system mass gate is invalid without flux accounting |
| `PARTICLE_ID_NOT_UNIQUE` | 1 | see per-case Q-I/Q-N audit |
| `VARIABLE_RESOLUTION_LINEAGE_AUDIT_REQUIRED` | 1 | particle identity and/or resolution zones change; lineage and zone-aware observables are required |

## Boundary

- Q-E external validation is not assessed because no external measurement/ground-truth binding was added in this dataset-only pass.
- Production eligibility remains zero until a later owner-approved scope and split contract consume these audits.
