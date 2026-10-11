# M1 upstream-first preparation

This directory contains only immutable upstream input copies, bounded reuse
audits, a predeclared observation contract, and a postprocessing command. It
does not contain native solver output and does not launch a solver.

## Exact inputs

F1 uses `f1/input/CaseDamBreak3D_Def.xml`, `elevation.txt`, `pressure.txt`,
and the official mDBC GPU script. F5 uses `f5/input/CasePistonBeach_REG_Def.xml`,
the official surface and velocity point files, the official GPU script, and
`CasePiston_SPHvsTheory.ods`. The source hashes and control values are in
`f5/input-manifest.json`; the copied files are byte-identical to the official
v5.4 package.

GenCase takes a definition base path and appends `.xml`. The valid command
form is therefore:

```bash
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64 \
  /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/main/09_WavesPiston/CasePistonBeach_REG_Def \
  '{attempt_root}/CasePistonBeach_REG' -save:all
```

The failed `gencase-001` receipt records the `.xml.xml` mistake; it is
preserved. Corrected `gencase-002` completed in `0.306 s` with 20,732 total
particles, 19,456 fluid particles, actual 2D evidence, and 2,670,524 output
bytes. Its solver input base is
`/data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/gencase-002/CasePistonBeach_REG`.
For 601 native saves, reserve 8 GiB and 1,800 s as a conservative starting
point; a linear BI4 scaling check from the existing v5.4 F5 run
`F5_RUNUP_00/F5_RUNUP_00_QUALIFICATION_004` (530,239 particles,
16,969,628 bytes per frame) gives about 399 MB for 20,732 particles across
601 frames before VTK and receipts. The root request and final receipt remain
authoritative.

## F1 reuse decision

`f1/reuse-audit.md` records the completed 601-frame legacy DUAL run and its
converted `trajectory.h5`. It is a valid toolchain diagnostic, but fails the
official mDBC identity gate (`Dp=0.012` dual-channel geometry versus the
official `Dp=0.01` single-tank obstacle case). It must not be used as the F1
official comparison result.

## F5 postprocessing

After the root-owned solver attempt passes, run:

```bash
lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m1/f5/scripts/extract_reference_observations.sh \
  /data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/<solver-attempt>/CasePistonBeach_REG \
  /data/nas/jade/Simulation/DualSPHysics/upstream-first/runs/F5/UF_F5_PISTON_REG/<postprocess-attempt>
```

The script runs the official PartVTK/PartVTKOut, MeasureTool, and IsoSurface
filters. Its two MeasureTool CSV files are the comparison inputs; VTK and
slice products are retained for geometry and visual QA. Compare the ODS and
simulation only on `[0,30] s`, report startup `[0,2) s` separately, and apply
the frozen primary gate on `[2,30] s` as stated in `observation-contract.md`.
