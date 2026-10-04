# F6 stage1 visual batch8 source handoff

This directory is a source-only handoff for the first eight independent F6 stage1 physical cases. It targets GPT-5.6 Luna/max, with no Gemini and no recursive agents. The authored scope contains no job launch, GenCase invocation, solver invocation, H5 output, BI4 copy, numeric particle array, PartVTK run, or animation render.

The batch is bound to one physical DP025 case per row. A DP value, native frame, floating-node export, saved view, or animation frame never creates another physical case. All rows remain `launch_allowed: false` and contribute zero to the independent-case count until root has performed actual preflight, fulltyped conversion, and visual review.

## Files

- `batch_param_table.json` records the eight independent physical parameter rows. The rows vary angular velocity, bounded square-body initial orientation, COM height, or horizontal placement. Body mass, inertia, fluid, tank, and six-degree-of-freedom lineage stay explicit.
- `fulltyped_binding.json` is the root-bindable owner metadata for the actual coarse native241 anchor. Its `physical_binding` is the allowlisted `ds-data-02.physical-binding.v1` object. Numerical spacing, typed ranges, native support mass, solver controls, and provenance remain outside that physical hash.
- `requests/fulltyped_dp025_anchor_request.json` is a strict-dispatch conversion skeleton. It points at the immutable source files, records SHA-256 inputs, and stays disabled until root review. It intentionally omits `--keep-validation-csv` so this source handoff does not request a CSV-array artifact.
- `source_provenance.json` records the native chain, exact source hashes, genuine failures, and unresolved frame-zero uncertainty.
- `audit-report.json` records source checks and the root gates.

## Native anchor

The anchor is `F6_ANGULAR_RELEASE_DP025` from the corrected actual coarse release. The provenance chain is:

1. GenCase actual source and XML in `root-angular-release-dp025-actual-gencase-preflight-017` (Gen017).
2. The completed native full12 GPU run in `root-angular-release-dp025-full12-native-gpu-021` (solver021), with 241 native states from physical time 0 through 12 s.
3. Native initial QA in `root-angular-release-dp025-actual-initial-qa-019` (QA019).
4. Semantic mass/configuration audit in `root-angular-release-dp025-actual-semantic-audit-v3-020` (semantic020).
5. Full241 same-UID body geometry and SO(3) comparison in `root-angular-release-full241-native-geometry-so3-three-dp-029` (actual body SO(3) root029).
6. Exact native timestamp alignment in `root-angular-release-full241-exact-native-time-geometry-so3-030` (root030).

The native typed contract is 417505 particles: 73441 fixed, 16384 floating (`Type=2`, `Mk=60`), and 327680 fluid (`Type=3`, `Mk=1`). The floating cohort is the immutable `(Zone, Idp)` identity across all 241 native parts. The actual body geometry report gives coarse centroid RMSE `1.1677086400117034e-09 m`, maximum centroid error `1.4104177250374626e-08 m`, maximum rigidity RMS `3.774058599973532e-06 m`, and maximum rigidity residual `7.582456991238951e-06 m`. These are descriptive source evidence; the report grants no Q-N or production claim, and the orientation budget remains unregistered.

## Mass and QA boundary

The physical rigid body is 128 kg with diagonal inertia `[8.53333333333, 8.53333333333, 13.6533333333] kg m2`. The native PartVTK support column sums to 256 kg because it represents a `0.256 m3 * 1000 kg/m3` support volume. The semantic audit also reports a derived uniform physical diagnostic node weight of `0.0078125 kg`, while the coarse solver interaction `masspart` is `0.015625 kg`. These quantities are deliberately kept separate. The native support column is preserved byte-for-byte and is never normalized to 128 kg.

QA019 therefore remains `overall_initial_qa_passed: false` because its rigid mass check compares 256 kg observed support mass with 128 kg declared physical mass. Semantic020 records `semantic_initial_qa_passed: true` only as a corrected interpretation of that support semantics; it does not turn QA019 into a physical, numerical, or visual pass. GenCase particles have zero velocity, and frame-zero propagation of the declared angular velocity through the solver remains unobserved.

## Negative evidence

The all3DP comparison remains a negative comparison with Q-N `not_assessed`. The genuine finer-half source comparison records center RMSE `0.11135030810216248 L` outside its generic 5% macro budget and SO(3) geodesic RMSE `0.07717270190734828 rad` outside that budget. The all3DP source also records maximum macro relative RMSE `0.6316608687244185`. These failures stay visible. No quarter-step cure, spatial prerequisite, integrator prerequisite, or precision acceptance is inferred from them.

## Root handoff

Root should review the native full241 visual evidence and the mass/QA boundary, perform actual continuous and generated-particle non-overlap preflight for all eight planned rows, bind any nonzero orientation to an explicit SO(3) representation, and then decide whether to enable the disabled anchor conversion request. Only root may launch it. Conversion output, typed H5, numerical acceptance, visual approval, Q-N, and production eligibility are absent from this source handoff.

The exact source paths and hashes are in `source_provenance.json`; no old mother geometry or unreviewed fallback is used as the native anchor.
