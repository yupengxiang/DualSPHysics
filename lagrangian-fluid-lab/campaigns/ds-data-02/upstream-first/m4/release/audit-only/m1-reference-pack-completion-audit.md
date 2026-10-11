# M1 reference-pack completion audit

Audit date: 2026-10-11.  This is an audit-only note for the current F1 and F5
reference packs.  It reads the small pack, receipt, manifest, and comparison
report metadata.  It does not read native frames/HDF payloads, scan or hash
large data, launch a worker, or change a card, status, receipt, ledger, or
source artifact.

## Finding

Both packs have real, reproducible comparison evidence and preserve the
diagnostic scientific boundary.  Neither current postprocess tree provides a
clean explicit postprocess-manifest handoff:

* F1's current manifest is explicitly recorded by
  `f1-reference-pack-v2.json` as `status=incomplete`, with
  `unexpected_postprocess_manifest_schema` and
  `manifest_elevation_hash_mismatch`.  The actual `comparison-002` receipt
  includes that manifest as an input.  I found no replacement manifest under
  the F1 postprocess attempt.  The corrected comparison supersedes the old
  invalid column mapping, but it does not supersede this upstream manifest
  defect.
* F5's current manifest is produced by the current `postprocess-001` run but
  points to `_elevation.csv` and `_velocity.csv`, which do not exist.  The
  real outputs are `_elevation_Elevation.csv` and `_velocity_Vel.csv`; the
  comparison receipt and report correctly bind those real files.  The pack's
  `postprocess_manifest_correction` records the corrected paths, but there is
  no standalone corrected manifest or hash-bound replacement in the run tree.
  Thus the comparison is usable and traceable at pack level, while the
  postprocess-manifest contract remains an explicit delivery gap unless the
  release contract accepts that pack field as its replacement.

These are current-run delivery issues, not merely preserved historical
failures.  The M1 status should therefore not be inferred from the successful
comparison exit codes or from a certificate alone.

## Evidence matrix

| Required M1 evidence | F1 `f1-reference-pack-v2` | F5 `F5_REFERENCE_PACK` |
| --- | --- | --- |
| Frozen inputs and version/command | Official v5.4 XML, point files, SPHERIC metadata/workbook, and the observation contract are hash-bound in the pack and comparison report. Actual GenCase receipt is `gencase-001`, `returncode=0`, 3D, followed by solver `solver-001`, `returncode=0`, command `DualSPHysics5.4_linux64 -gpu:0 -mdbc ...`. | `m1/f5/input-manifest.json` binds the v5.4 XML, probe files, ODS, and official script. Actual `gencase-002` is `returncode=0`, 2D with 20,732 particles; `solver-001` is `returncode=0`, command `DualSPHysics5.4_linux64 -gpu:0 ...`. |
| Real upstream outputs and postprocessing | Solver output exists. `postprocess-001` completed with the official MeasureTool extraction command and produced the elevation and pressure CSVs. `comparison-002` completed with `compare_spheric_reference_v2.py`, `returncode=0`, report schema `ds-data-02.upstream-first.f1-spheric-comparison.v2`. | Solver output exists. `postprocess-001` completed with the official extraction script and produced the actual suffixed MeasureTool CSVs. `comparison-001` and `wave-comparison-001` both completed with `returncode=0` and produced their reports. |
| Primary and auxiliary observations | Primary H1–H4 elevations are bound by exact `Elevation_<n> [m]` headers plus XY; auxiliary P1–P8 pressures are bound by exact `Press_<n> [Pa]` headers plus XYZ. No positional fallback; missing counts are zero. | Primary surface eta at x=6 m; auxiliary surface propagation at x=5/7 m and velocity x/z at x=6 m, z=0.4 m. The report has 601 samples for the real elevation/velocity CSVs and binds all five comparison series. |
| Reference curves | SPHERIC Test 02 workbook (`Experimental_data`, source bracket about `0.000022..7.394064 s`) plus explicit coordinate metadata and x-reflection. The report records source URL/file hashes and H4 reservoir mapping. | ODS `REGULAR_BEACH` second-order Stokes and prior SPH columns, plus the separate official `WavePaddle_mkb0010.csv` supplemental analytical reference. ODS populated bracket is `[0,15] s`; the supplemental reference is `[0,40] s` and does not replace the ODS result. |
| Difference and applicable scope | Report uses native times, interpolation only inside the SPHERIC bracket, one excluded sample/channel, 599 matched samples, no retiming or extrapolation. Full-run pressure integrals are explicitly documented. Report status is diagnostic-only; no source uncertainty or acceptance tolerance is claimed. | ODS comparison uses actual common primary `[2,15] s` and excludes 300 requested `[2,30] s` samples; no phase shift or extrapolation. Supplemental full-window metrics are separately labeled analytical diagnostic. Pack/report status remains `calibration_2d`/diagnostic, with no 3D or product acceptance credit. |

## F1 concrete checks

The corrected comparison is real and scientifically bound.  The receipt
command reads the two actual NAS MeasureTool CSVs, the SPHERIC workbook, and
`spheric-test2-metadata.json`; its input list also includes the solver receipt,
postprocess receipt, and postprocess manifest.  The report records all four
height and eight pressure channels, 599/600 matched samples, and the source
bracket `[2.19299528509964e-05, 7.3940635356423] s`.  Representative actual
diagnostics are H1 RMSE `0.153322 m`, H4 RMSE `0.0467282 m`, and P1 RMSE
`1230.31 Pa`; these are reported as diagnostics, not acceptance results.

The old `comparison-001` report is explicitly
`INVALID_COLUMN_MAPPING_DO_NOT_USE` and has a veto document.  The
`comparison-002` exact-header/coordinate binding is the valid comparison, so
that historical scientific failure is correctly superseded.  The manifest
issue is different: the only current F1 manifest is
`ds-data-02.upstream-first.f1-minimal-postprocess.v1`, while the pack records
it as incomplete for the two reasons above.  There is no actual corrected
manifest artifact to replace it, and the valid comparison receipt still
consumed the incomplete manifest.  F1 therefore has a complete diagnostic
comparison payload but not a complete explicit upstream postprocess handoff.

Evidence paths:

* Pack: `m1/f1/evidence/f1-reference-pack-v2.json`
* Postprocess receipt: `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DAMBREAK3D/postprocess-001/execution-receipt.json`
* Current manifest: `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DAMBREAK3D/postprocess-001/observations/postprocess-manifest.json`
* Valid comparison receipt/report: `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DAMBREAK3D/comparison-002/execution-receipt.json` and `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F1/UF_F1_MDBC_DAMBREAK3D/comparison-002/comparison/spheric-comparison-report.json`

## F5 concrete checks

The actual F5 chain is complete through comparison execution.  The ODS
receipt binds the two real MeasureTool CSVs, `CasePiston_SPHvsTheory.ods`,
the observation contract, and the comparator.  Its report records eta x5/x6/x7
and both velocity components, preserves physical propagation order, and uses
the actual common primary window `[2,15] s`.  The ODS report marks the primary
gate as `insufficient_reference_coverage` because 300 samples from the
requested `[2,30] s` interval have no ODS values.  Actual common-primary RMSE
values are eta-x6 `0.0219737 m`, VelX `0.0729883 m/s`, and VelZ `0.0421460
m/s`; they remain diagnostic under the frozen limits.

The WavePaddle supplemental receipt/report uses the real
`WavePaddle_mkb0010.csv` and `[2,30] s` simulation window.  It explicitly
preserves the immutable ODS negative coverage and does not replace it.  Its
eta RMSE is `0.0158907 m` against the frozen `0.015 m` diagnostic limit, and
the report labels the result supplemental analytical diagnostic only.  This
is sufficient evidence for the requested reference curves and applicability
limits, not an experimental or 3D qualification.

The manifest defect is independently observable without reading payloads:
the current F5 manifest names
`.../measuretool/_elevation.csv` and `.../measuretool/_velocity.csv`, both
absent, while the actual files named by the pack and consumed by both
comparison receipts are `.../_elevation_Elevation.csv` and
`.../_velocity_Vel.csv`.  The F5 extraction script writes the former names
statically, explaining why the current manifest is stale.  The pack-level
correction makes the real comparison traceable, but it does not itself create
a corrected manifest with source/output hashes.

Evidence paths:

* Pack/input contract: `F5_REFERENCE_PACK.json`, `m1/f5/input-manifest.json`, `m1/observation-contract.md`
* Postprocess receipt/manifest: `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/postprocess-001/execution-receipt.json` and `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/postprocess-001/observations/postprocess-manifest.json`
* ODS receipt/report: `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/comparison-001/execution-receipt.json` and `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/comparison-001/comparison/comparison-report.json`
* Supplemental receipt/report: `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/wave-comparison-001/execution-receipt.json` and `/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/wave-comparison-001/comparison/wave-generator-supplemental-report.json`

## Release implication

Keep the scientific negative claims and diagnostic/QNQE limits exactly as
reported.  Before treating M1 as an explicitly complete upstream-reference
delivery, bind a corrected F1 manifest and a corrected F5 manifest (or a
clearly hash-bound replacement artifact) to the packs.  The existing actual
comparison receipts/reports establish the observations and curves, but a
successful downstream comparison does not by itself prove that the required
postprocess manifest delivery exists.
