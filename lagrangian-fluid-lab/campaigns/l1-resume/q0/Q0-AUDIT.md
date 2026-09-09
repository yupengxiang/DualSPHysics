# Q0 — finite-wall and runtime-domain re-audit

## Scope

Q0 reran the retained nine W1 space HDF5 products and the retained W2-A HDF5
through the production `r5.audit_hdf5` → `r6.full_time_audit` chain. The old
campaign was not modified. Endpoint geometry now distinguishes the five finite
closed faces from the open top; an explicitly declared runtime AABB is a
separate diagnostic. Adjacent saved frames additionally report outward
finite-face/obstacle crossings as saved-frame intervals. The interpolated
fraction is a chord locator, not an exact continuous particle event.

Machine-readable evidence is in
[`REVISED_AUDIT_SUMMARY.json`](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/q0/REVISED_AUDIT_SUMMARY.json). Full per-case audit payloads are retained under the ignored
`campaigns/l1-resume/artifacts/q0-revised-audits/` directory.

## Results

| retained case | revised result | finite-wall finding | lifecycle finding |
|---|---|---|---|
| W1 h09 coarse | pass | none | no missing identities |
| W1 h09 medium | pass | none | no missing identities |
| W1 h09 fine | failed | front/back endpoint excursions begin at 0.382011 s; 2 particles, 0.002 kg | no missing identities |
| W1 h10 coarse | pass | none | no missing identities |
| W1 h10 medium | pass | none | no missing identities |
| W1 h10 fine | failed | front/back endpoint excursions begin at 0.379018 s; 2 particles, 0.002 kg | no missing identities |
| W1 h11 coarse | pass | none | no missing identities |
| W1 h11 medium | pass | none | no missing identities |
| W1 h11 fine | failed/unknown | 52 endpoint-penetration frames; first saved-frame chord event is right-face crossing in `[0.386017, 0.387004]` s, 2 events, 0.002 kg | 352 native solver position exclusions; classified as solver exclusions only |
| W2-A h11 fine | failed/unknown | bottom endpoint excursions begin at 0.130014 s; 1,371 frames; maximum outside mass 17.427000827738084 kg | 49,769 native solver position exclusions; classified as solver exclusions only |

The top opening was not promoted to a wall in any of these results. The h11
fine chord event is new evidence that endpoint-only checks had missed a
right-face event between saved outputs; its time is explicitly interval-valued.

## Initial-mass reconciliation

For the H10 W1 ladder, the retained initial fluid masses are:

| resolution | `dp` | initial mass |
|---|---:|---:|
| coarse | 0.020 m | 58.75200279057026 kg |
| medium | 0.014 m | 58.216702714562416 kg |
| fine | 0.010 m | 54.285002578399144 kg |

The medium-to-fine drop is 6.753560323470175%. This is recorded as a
resolution/discretization confound, not silently treated as solver mass loss.

## Verification

The finite-wall module has direct tests for above-rim lateral motion, a low
side-wall crossing, a top-before-side trajectory, and an obstacle crossing.
The R5/R6/Q0-Q2 targeted suite passed 21 tests after the production
integration.
