# F5 stage 1 native filled-bed repair options

This fresh handoff records two bounded source changes for the F5 compact
runup bed.  It is a recipe review only.  It does not edit Def050, regenerate
GenCase output, read H5 arrays, run a solver, convert BI4, or render frames.
Root037's completed full801 result remains the immutable failure ledger; no
root cause is assigned before the 058 native Type-0 audit is reviewed.

The bound sources are the actual Gen050 XML/Def050 and the same continuous-bed
STL used by the original013 case.  In both source files:

- lines 27--241 hold the explicit 52-triangle bed mesh under `setmkbound
  mk="40"`; its top strips follow x/z nodes `(-0.2,0)`, `(2,0)`, `(3,0.28)`,
  `(3.6,0.448)`, `(3.9,0.448)`, `(4.4,0.05)`, `(4.8,0.05)` across
  `y=-0.15..0.15`, and the lower closure is at `z=-0.15`;
- lines 269--271 set `mk=40`, draw
  `assets/f5_compact_continuous_bed_profile.stl`, and emit `shapeout`;
- line 272 returns to `setmkfluid mk="0"`; lines 273--281 preserve the current
  fluid clip and initial fill;
- generated XML lines 373--387 retain the original particle ranges and
  `mk=40` is the fixed range beginning at Idp 5020 with count 149532.

The two candidates in `repair_options.json` are deliberately limited to bed
geometry representation:

1. **Explicit mesh only.** Keep the existing 52 triangle commands unchanged
   and remove only lines 269--271 (`setmkbound`, `drawfilestl`, and
   `shapeout`).  This
   removes the external STL geometry path while retaining the same profile,
   y extent, lower closure, `mk=40`, fluid fill, motion, gauges, domain, and
   physics.  A fresh GenCase must prove the mesh creates a native Type-0
   `mk=40` cohort before this candidate is considered.
2. **Profile mesh plus an explicit mk=40 underlay.** Keep the current mesh and
   STL, then insert a `drawbox` immediately before line 272 with
   `setmkbound mk="40"`, `boxfill=solid`, point `(2.00,-0.15,-0.15)`, size
   `(2.80,0.30,0.15)`, and `layers vdp="0,1,2"`.  This adds a bounded native
   support volume below `z=0` only on the sloped/crest interval x=2..4.8;
   the exact continuous profile remains the upper boundary supplied by the
   existing mesh/STL.  Fresh initial QA must reject the candidate if the
   underlay creates duplicate or overlapping native particles with the floor.

Each candidate requires its own fresh GenCase and initial typed QA, with new
XML/Def/STL or generated geometry hashes, fixed/moving/fluid counts, exact
`mk=40` range provenance, and frame-zero fluid/profile overlap diagnostics.
No solver launch, conversion, amplitude batch, or production approval is
included.  Root may discard both options after the 058 audit.

The request is `kind=cpu`, `cpu_task_kind=audit`, and
`launch_allowed=false`; only Root may authorize a later GenCase/initial-QA
execution.
