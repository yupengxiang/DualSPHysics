# Q1 — same-version official mDBC control

## Purpose

Q1 establishes a raw positive control from the untouched DualSPHysics v5.4
mDBC examples. It is an asset and execution control, not an L1 qualification
and not evidence that the L1 boundary geometry is correct.

The machine-readable manifest is
[`Q1-OFFICIAL-RESULTS.json`](Q1-OFFICIAL-RESULTS.json). Generated products and
the raw solver attempt are intentionally ignored by the repository policy; the
manifest records their paths and source hashes.

## Source and preparation

The inventory used the same-version tree at
`vendor/official/DualSPHysics_v5.4`. The official XML sources were not edited:

| case | official source | GenCase total | bound | fluid | non-zero normals | final zero normals |
|---|---|---:|---:|---:|---:|---:|
| 3-D DamBreak mDBC | `examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml` | 1,015,809 | 363,597 | 652,212 | 363,597 | 0 |
| StillWedge LR | `examples/mdbc/01_StillWedge/CaseStillWedgeLR_Def.xml` | 3,027 | 580 | 2,447 | 580 | 0 |
| StillWedge HR | `examples/mdbc/01_StillWedge/CaseStillWedgeHR_Def.xml` | 11,250 | 1,144 | 10,106 | 1,144 | 0 |

The inventory also fingerprints the v5.4 binaries, version file, official GPU
and CPU scripts, and XML geometry/parameter structure. All three official
GenCase preparations completed successfully.

## Raw positive-control run

The official 3-D DamBreak case was run once with the official GPU executable
and `-mdbc` on allowlisted GPU 4. The source case uses `TimeMax=6` and
`TimeOut=0.01`.

| item | result |
|---|---|
| solver status | completed, return code 0 |
| elapsed time | 2,439.113745564129 s (0.6775315959900359 GPU h) |
| guard/timeout/interruption | none |
| required solver text | found |
| raw frames | 601 (`Part_0000.bi4` … `Part_0600.bi4`) |
| raw BI4 evidence | 19,529,195,271 bytes |
| auxiliary evidence | `Run.out` 91,105 bytes; `Run.csv` 1,044 bytes |

The attempt directory is recorded in the JSON manifest:
`campaigns/l1-resume/runs/q1-official/official_dambreak3d_mdbc/attempts/`.
The raw run was deliberately not normalized to HDF5 because Q1 only answers
whether the untouched official recipe can generate a complete raw control.

## Interpretation and gate

Q1 passes as an execution-control diagnostic: the same-version official mDBC
assets generate a complete raw sequence with no resource-policy violation.
It does not pass or fail the L1 physical-wall gate, because the official raw
control was not used as an L1 test case. Q2 was therefore launched as the
separate bounded bridge from the official complete recipe to the retained L1
geometry.
