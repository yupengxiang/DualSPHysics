# F5 fresh069: bed fill contract diagnosis and candidate B

This handoff is source-only. It records the actual Root131 negative result and prepares one bounded candidate B plus a disabled frame-zero distribution audit. It does not read BI4/H5/CSV arrays, start GenCase, start DualSPHysics, convert, render, or authorize full801.

## Actual negative evidence retained

Candidate A061 was genuinely generated (Root075), passed the 14 initial QA checks (Root083), and then failed the real 51-frame bed audit (Root131). At t=0.5000603704 s, 10170/40710 fluid rows were below 1 DP, 9118 were below 2 DP, and maximum depth was 0.5023042402 m. At t=1.0000641873 s, 13395/40710 (32.903%) were below 1 DP, 12257 (30.108%) below 2 DP, and maximum depth was 0.5562836166 m. UID loss and nonfinite rows were zero. This is a physical failure, not a structural gate result; full801 remains disabled.

A removed only the duplicate/historical `drawfilestl`/`shapeout` path. The retained explicit 52-triangle mesh is closed in source geometry and uses the exact profile nodes, y extent, lower closure, DP, fluid clip and motion. The metadata cannot prove that the remaining failure is missing geometry, an STL fill issue, or boundary/solver behaviour. The Root057 `mk=40` cohort contains walls, so it is support evidence only and is not a bed-only claim.

## Candidate B

B keeps the exact mesh and all physical controls, then makes the fill/rasterization contract explicit: `solid` is used for the physical floor/walls/piston, the exact bed triangles are drawn first in `full`, `solid` is restored before the physical boxes, and the retained closed STL is drawn in `full` with the official `autofill=true` flag before `shapeout`. This follows the local official template/closed-STL example and the historical F5 surface-first/full-mesh source patterns. It adds no underlay, does not change the bed, does not alter any penetration threshold, and does not change runtime/mDBC settings. Actual particle counts and support remain unknown until Root performs a fresh genuine GenCase and typed QA.

## Root execution order

1. Review `gencase-request.json` and the source hashes, then manually enable only the fresh genuine B GenCase into a new DATA attempt.
2. Bind `initial-qa-manifest.json` to the actual B GenCase receipt and manually enable the disabled typed QA request. It must report the actual total and pass finite/type/positive-mass/3D checks; its result is still not bed completeness.
3. Bind the actual generated XML/receipt and typed frame-zero H5/XDMF products to `initial-bed-distribution-request.json`; fill actual hashes and keep the request disabled until the binding is complete.
4. Run the worker once as a CPU read-only audit. It reports XML-range support, mixed mk40 warning, exact profile surface bands (0.5/1/2 DP), six x segments and y levels, finite/UID/duplicate/overlap checks, and initial fluid below-profile rows.
5. Interpret the result manually. Frame-zero support can distinguish missing/discretized bed support from a later boundary/solver failure, but it cannot authorize a dynamic event. A later short event would still be required before any full16 decision; no full16 request is included here.

The worker's `--check` is bounded synthetic data only. Future real invocation reads arrays read-only and writes only its report directory.
