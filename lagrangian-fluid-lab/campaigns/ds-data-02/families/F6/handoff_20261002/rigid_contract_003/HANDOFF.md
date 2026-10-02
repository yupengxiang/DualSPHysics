# F6 RIGID003 CPU evidence handoff

This is an additive repair scope for the F6 floating-body mother.  The
previous commensurate mother left `center` and `inertia` implicit in `Def.xml`.
GenCase therefore derived the native aggregate from resolution-dependent body
particles: its generated XML reported coarse `(2.4, 1.2, 1.08)` with inertia
`(10.5813, 10.5813, 16.384)`, medium `(2.4, 1.2, 1.10)` with
`(9.81333, 9.81333, 15.36)`, and fine `(2.4, 1.2, 1.08)` with
`(9.55733, 9.55733, 15.0187)`.  Those old XML and audits remain unchanged.

The official GenCase XML contract accepts `center` and diagonal `inertia`
children under `<floatings><floating>`.  RIGID003 uses that contract in all
six new Def files while keeping the same continuous tank, fluid box, finite
walls, initial body placement, fluid population rule, and body mass:

* continuous fluid box: low `(0.4, 0.4, 0.04)`, size `(4.0, 1.6, 0.8)`,
  volume `5.12 m^3`, mass `5120 kg`;
* floating type: `2`, aggregate `massbody=128 kg`, center `(2.4, 1.2,
  1.08) m`;
* analytic box inertia: `(8.533333333333335, 8.533333333333335,
  13.653333333333336) kg m^2`;
* fixed physical wall endpoints and three-dimensional cell-centre fluid;
  the wave case has actual moving paddle particles.

The completed CPU receipts are the six `*_GENCASE_001` and six
`*_PARTVTK_003` receipts under
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F6/`.  The actual
GenCase counts are:

| mechanism | DP | total | fluid | floating | moving |
| --- | ---: | ---: | ---: | ---: | ---: |
| simple free response | 0.08 | 16126 | 10000 | 726 | 0 |
| simple free response | 0.05 | 59737 | 40960 | 2601 | 0 |
| simple free response | 0.04 | 113832 | 80000 | 4851 | 0 |
| no-contact wave | 0.08 | 17402 | 10000 | 726 | 1276 |
| no-contact wave | 0.05 | 64531 | 40960 | 2601 | 4794 |
| no-contact wave | 0.04 | 123744 | 80000 | 4851 | 9912 |

`strict_rigid_contract_audit_002.json` reads every generated XML and verifies
the actual massbody and center, and that all six native inertia triplets are
exactly the GenCase serialized contract `(8.53333, 8.53333, 13.6533)` while
remaining within `5e-5 kg m^2` of the analytic physical values.  The fixed
precision distinction is explicit: the serialized XML values are output
rounding, and are not a different body at any DP.  The earlier exact-float
failure is preserved as `strict_rigid_contract_audit_001_failed.json` rather
than rewritten.

The additive `qualification_request_manifest_002.json` contains six
root-only requests with attempt IDs ending `_SOLVER_QUAL_003`.  Each uses the
completed GenCase directory as `cwd`, binds the GenCase/PartVTK receipts and
all source/control/native/normal/binary hashes, and runs a complete 0--12 s
window at 0.05 s output spacing.  Medium requests are:

* `qualification_requests_002/F6_HANDOFF_20261002_SIMPLE_FREE_RESPONSE_RIGID003_MEDIUM.json`
  (59737 total, 40960 fluid);
* `qualification_requests_002/F6_HANDOFF_20261002_WAVE_NO_CONTACT_RIGID003_MEDIUM.json`
  (64531 total, 40960 fluid, 4794 moving).

These are runnable requests only.  GPU dispatch, FloatingInfo/ComputeForces
post-processing, complete-window native state checks, Q-N, and production
remain pending root review.
