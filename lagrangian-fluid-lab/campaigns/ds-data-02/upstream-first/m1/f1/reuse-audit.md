# F1 official mDBC DamBreak3D reuse audit

Audit date: 2026-10-11. This is a bounded metadata and path audit. No native
particle array was opened by this audit.

## Exact 601-frame candidate found

The only completed 601-frame candidate located under the DS-DATA-02 data root
is the following legacy DUAL case:

```text
raw solver output:
/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_REF_DUAL_NOMINAL_MEDIUM/qualification-ref-dual-medium-v1/F1_REF_DUAL_NOMINAL_MEDIUM

native frames:
/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_REF_DUAL_NOMINAL_MEDIUM/qualification-ref-dual-medium-v1/F1_REF_DUAL_NOMINAL_MEDIUM/data/Part_0000.bi4 ... Part_0600.bi4

raw execution receipt:
/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_REF_DUAL_NOMINAL_MEDIUM/qualification-ref-dual-medium-v1/execution-receipt.json

completed native conversion:
/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_REF_DUAL_NOMINAL_MEDIUM/native-conversion-reference-004/trajectory.h5
/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_REF_DUAL_NOMINAL_MEDIUM/native-conversion-reference-004/conversion-report.json
```

The raw receipt records 601 saves over `0..6 s`, `TimeOut=0.01`, 319.64 s
solver wall time, and 12,407,422,295 bytes. The conversion report records
601 frames, 643,866 particles at frame zero, 643,822 at frame 600,
`t_last=6.000033453762057 s`, a completed conversion, and successful PartVTK
checks at frames 0, 300, and 600. The converted HDF5 is 8,408,245,101 bytes.
These paths are useful diagnostic data and are retained as immutable evidence.

## Why the candidate is not an official mDBC reuse

The candidate's own conversion metadata identifies it as
`official_v54_asymmetric_dual_channel`, with control family
`F1_CONTROL_ASYMMETRIC_DUAL_CHANNEL_V1` and geometry family
`F1_GEOM_ASYMMETRIC_DUAL_CHANNEL_V1`. Its generated controls include
`Dp=0.012`, an initial depth of `0.55 m`, lower/upper channel widths of
`0.34/0.60 m`, a separator, and a dual-channel fluid volume of `0.616 m^3`.
The first missing fluid IDs occur at frame 331; the report therefore also
marks the conversion as evidence only and gives no Q-N or production claim.

The official upstream target is
`examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml`, whose immutable input
hash in this worktree is:

```text
1f7cca807e16a3b1a1cc4da649a68db5166439d3f4b30fa4ea25635baf6045b7
```

It is a single tank with the official mDBC obstacle and `Dp=0.01 m`; its
geometry, initial fill, and physical control are different from the candidate.
The candidate consequently fails the exact-reuse gate on case identity,
geometry, resolution, and initial condition. Do not compare its histories to
the official mDBC result as if they were the same physical case. A fresh
official run is required; the old 601-frame data may be used only for toolchain
or plotting diagnostics.

## Other conversion evidence

`native-conversion-reference-002` and `native-conversion-reference-003` are
failed 3600 s attempts (`reserved_wall_time_exceeded`) and are not complete
reuse products. The completed `reference-004` conversion above is the only
candidate that should be cited for the 601-frame diagnostic.

## Fresh-run input contract

The prepared immutable copies for the official run are under `input/`:

```text
input/CaseDamBreak3D_Def.xml
input/elevation.txt
input/pressure.txt
input/xCaseDamBreak3D_mDBC_linux64_GPU.sh
```

The official script's primary elevation probes are H1 `(0.496,0.5,0)`, H2
`(0.992,0.5,0)`, H3 `(1.488,0.5,0)`, and H4 `(2.638,0.5,0)`. Its auxiliary
pressure probes are the eight points recorded in `pressure.txt`; the fresh
postprocessor must preserve those coordinates and the native solver times.
