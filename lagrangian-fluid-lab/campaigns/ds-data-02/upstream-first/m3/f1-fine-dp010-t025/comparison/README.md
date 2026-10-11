# M3 fine mother-versus-water-depth comparison

This directory contains the comparison worker and runner request templates for
the two original-resolution F1 depth children:

| case | physical depth | `dp` | `TimeOut` | comparison role |
|---|---:|---:|---:|---|
| `UF_F1_MDBC_DAMBREAK3D` | 0.55 m | 0.01 m | 0.01 s | accepted fine mother |
| `UF_F1_MDBC_DP010_H050` | 0.50 m | 0.01 m | 0.025 s | M3 water-depth child |
| `UF_F1_MDBC_DP010_H060` | 0.60 m | 0.01 m | 0.025 s | M3 water-depth child |

`compare_mother_waterdepth_v1.py` imports the strict CSV parser from
`m1/f1/scripts/compare_spheric_reference_v2.py`; it does not copy or alter the
M1 implementation. The child is evaluated at its native MeasureTool times and
the mother history is linearly interpolated only inside the native common
bracket. Every H1-H4 elevation and P1-P8 pressure channel must cover the full
0..6 s window in both cases. A missing endpoint, nonfinite value, duplicate
time, ambiguous header/coordinate binding, or incomplete channel aborts the
worker.

The physical fill-height change and the output-sampling change are recorded in
separate report fields. The `.50`/`.60` difference is the M3 physical axis;
the mother `.01 s` versus child `.025 s` `TimeOut` difference is a separate
numerical/output-sampling difference. The worker does not retime, phase-shift,
extrapolate, or grant equivalence credit. It reports diagnostic metrics only:
there is no experimental credit, no Q-E/Q-N claim, and no acceptance threshold.
H/P are numerical MeasureTool observations here; the SPHERIC experimental
reference is not read by this worker.

The mother input is gated by
`m3/fine-mother-acceptance-decision.json`, which records the all-601-frame
native identity/finite scan and scoped internal numerical-use acceptance. The
request templates remain `template_pending_actual_receipts` and are immutable.
`finalize_m3_requests_v1.py` reads a completed child solver receipt, checks the
template hash, and writes review candidates only below `comparison/candidates/`.
It never calls the shared runner and never writes the campaign request
directory. The postprocess candidate includes runtime v2 and v6, official
`DsphConfig.xml`, the extractor inputs, the exact solver receipt SHA256, and
every non-hidden regular file in the completed native solver attempt.

The helper materialized
`candidates/UF_F1_MDBC_DP010_H050-postprocess.ready.json` after the H050 solver
receipt reached `completed`; its receipt SHA256 is bound in the candidate. The
comparison candidate remains absent until the child v2 postprocess receipt,
manifest, and both H/P CSVs exist and agree with the completed mother sources
and all-601 scoped acceptance decision. The sibling finalization report records
this pending state. H060 remains receipt-gated in the same helper and is not
launched here.

Run order after root records the real child receipts:

1. Submit the child postprocess template through the shared runner. It calls
   the existing `extract_reference_observations_v2.sh`, producing the two small
   MeasureTool CSVs and a v2 postprocess manifest.
2. Submit the matching comparison template through the shared runner. It reads
   the mother and child CSVs, receipts, manifests, immutable definitions, the
   child manifest, the strict M1 parser, and the mother acceptance decision.
3. Preserve the report, aligned CSV, summary CSV, and all input hashes. A
   comparison report is not a child acceptance decision.

The worker reads only the CSV and metadata paths named by a request. It does
not read native `Part_*.bi4` frames, write to raw solver attempts, or invoke a
solver/GenCase/postprocessor. Requests use the canonical original-project
environment at `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python`.
