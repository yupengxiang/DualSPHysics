# F5 A061 short event and 51-frame bed audit (064)

This is a fresh, source-only handoff for the single selected Candidate A
repair.  It does not claim that the duplicate STL invocation repair works.
The only valid physical evidence before this scope is the genuine A061
GenCase receipt 075 and the actual initial QA receipt/report 083:

- GenCase 075 is completed, 3-D, \`total_particles=214385\`,
  \`fluid_particles=40710\`.
- QA 083 is completed with all fourteen initial checks true.  Its native
  fluid mass is reported as \`325.680016284 kg\` versus the continuum
  \`325.714285714 kg\`; no rescaling was performed.
- 080, 081, and 082 are historical failed attempts and are not inputs to this
  scope.  082 reached all checks but failed only while serializing a NumPy
  boolean.  083 is the corrected actual run.

Both requests are disabled (\`launch_allowed=false\`).  Root must recompute the
registered hashes after the real short solver and native conversion exist,
then make the final launch decision.  The intended order is:

1. Root reviews and enables \`short-event-solver-request.json\`, which runs the
   genuine A061 generated prefix for \`-tmax:1.0 -tout:0.02\` into the fresh
   064 \`solver_output\` directory.
2. Root converts that solver output with the existing strict native conversion
   path into the exact \`native_conversion_output_root\` recorded in
   \`binding.json\`, and publishes 51 H5 frames plus the XDMF time axis there.
   This handoff does not run the converter.
3. Root binds the completed solver receipt, conversion report, H5 SHA, and
   XDMF SHA in \`binding.json\` and \`bed-audit-request.json\`, recomputes every
   \`input_sha256\` entry, and enables the CPU audit request.

\`worker.py\` is read-only with respect to native input.  Its \`--check\` mode is
source-only and opens no BI4, CSV, H5, XDMF, solver output, or PartVTK.  A real
run first verifies the actual 075 GenCase receipt, actual 083 QA receipt and
report, completed 1-second solver receipt, and completed 51-frame conversion
metadata.  It then scans every saved H5 frame and writes
\`a061-short-event-bed-footprint-audit.json\`.

The penetration calculation follows the Root037 geometry logic with the A061
source profile exactly:

- x profile nodes are \`(-0.2,0)\`, \`(2,0)\`, \`(3,0.28)\`, \`(3.6,0.448)\`,
  \`(3.9,0.448)\`, \`(4.4,0.05)\`, \`(4.8,0.05)\`;
- penetration rows must be finite current valid Type-3 fluid rows inside that
  exact x domain and inside the actual bed footprint \`-0.15 <= y <= 0.15\`;
- every frame reports 1 DP (\`0.02 m\`) and 2 DP (\`0.04 m\`) counts, ratios to
  the complete frame-zero fluid UID set, ratios to current valid Type-3
  fluid, ratios to the finite bed-footprint denominator, deepest depth and
  deterministic samples;
- the complete initial Type-3 UID set remains the reference denominator.
  Per frame, missing/extra UID sets and nonfinite positions are reported with
  count, digest, and samples, and their cause remains explicitly
  unexplained.  No row is silently dropped or used to relax a penetration
  threshold.

The output is diagnostic evidence only.  It does not grant Q-N, production
approval, full-16-second authorization, or visual acceptance.  Passing this
short event would only justify Root's separate decision about a full 16-second
run.
