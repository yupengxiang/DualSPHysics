# F3 fresh107: internal pitch/AY source handoff

This package defines 16 new, disabled F3 source conditions for the prospective
48-case set. It uses pitch multipliers `0.9` and `1.1`, each crossed with
AY values `0.29, 0.36, 0.43, 0.50, 0.54, 0.57, 0.64, 0.70`:

- `F3_STAGE1_DP006_P0900_AY0290`: pitch=0.9, AY=0.29
- `F3_STAGE1_DP006_P0900_AY0360`: pitch=0.9, AY=0.36
- `F3_STAGE1_DP006_P0900_AY0430`: pitch=0.9, AY=0.43
- `F3_STAGE1_DP006_P0900_AY0500`: pitch=0.9, AY=0.5
- `F3_STAGE1_DP006_P0900_AY0540`: pitch=0.9, AY=0.54
- `F3_STAGE1_DP006_P0900_AY0570`: pitch=0.9, AY=0.57
- `F3_STAGE1_DP006_P0900_AY0640`: pitch=0.9, AY=0.64
- `F3_STAGE1_DP006_P0900_AY0700`: pitch=0.9, AY=0.7
- `F3_STAGE1_DP006_P1100_AY0290`: pitch=1.1, AY=0.29
- `F3_STAGE1_DP006_P1100_AY0360`: pitch=1.1, AY=0.36
- `F3_STAGE1_DP006_P1100_AY0430`: pitch=1.1, AY=0.43
- `F3_STAGE1_DP006_P1100_AY0500`: pitch=1.1, AY=0.5
- `F3_STAGE1_DP006_P1100_AY0540`: pitch=1.1, AY=0.54
- `F3_STAGE1_DP006_P1100_AY0570`: pitch=1.1, AY=0.57
- `F3_STAGE1_DP006_P1100_AY0640`: pitch=1.1, AY=0.64
- `F3_STAGE1_DP006_P1100_AY0700`: pitch=1.1, AY=0.7

The four Root839 full836 visual corners released the boundary
`pitch=[0.8,1.2]`, `AY=[0.25,0.75]`. That evidence supports source construction
inside the rectangle; it does not approve these internal points, award case
credit, grant Q-N, or certify numerical precision.

The input-preparation contract reuses the reviewed true-v1
`amplitude_x`/`amplitude_y` transformer and the exact Gen056/QA058 DP006
initialization proven by Root704/705. The source contract retains the reference
population `179208` total (`67500` fluid, `111708` fixed, `0` moving), 3D
metadata, DP `.006`, `tmax=8.35`, `tout=.01`, `836` saved frames, and the
unchanged `-mdbc_noslip:1` solver recipe. Only the pitch and AY controls vary.

`requests/batch-source-preparation-request.json` is a disabled Root-owned CPU
registration for the frozen input-preparation builder. The per-case records in
`requests/input-preparation/` bind every condition to that batch and keep the
future report, forcing, generated XML/BI4, GenCase receipt, and all downstream
receipt hashes null. The package does not invoke GenCase, a solver, conversion,
rendering, or any scientific payload reader. Root's registered worker must
materialize and attest new forcing/condition hashes before any later gate.

Run the metadata-only validator:

```text
python3 -B validation/validate_fresh107.py
```

The validator reads package JSON and source code only. It does not open or hash
BI4, H5, CSV, DAT, VTK, or solver outputs.
