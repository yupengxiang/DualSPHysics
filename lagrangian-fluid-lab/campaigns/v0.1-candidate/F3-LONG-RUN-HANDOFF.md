# F3 Long-Run continuation handoff

Baseline: `a8e5038a0600efbd67b1f5578649d225fee97e4f` (reviewer package dated 2026-09-10).

## Current evidence

The repository contains six repaired F3 input cases (plain/baffled at 0.03, 0.015 and 0.01 m) with completed solver attempts and normalized trajectory artifacts. These are diagnostic evidence only. The older failed attempts remain preserved. No 0.0075 m or 0.006 m plain reference run has been executed yet, so the requested F3 production recipe is not qualified.

The attached reviewer package requires the following sequence: calibrate observation discretization and frame semantics; freeze a long horizon and output cadence; run the plain reference ladder 0.010/0.0075/0.006 m; qualify a candidate recipe over the declared time window and coordinate frame; then run 0.9/1.0/1.1 drive endpoints and an independent 0.97 interior point before development production, material transport, and training.

## Reproducibility contract to implement

- Domain: F3 `F3_3D_CELL2`, plain background first.
- Registered resolutions: `dp = 0.010, 0.0075, 0.006 m`; legacy 0.015 and 0.030 m remain historical evidence.
- Long-window observations: use native saved frames only, report actual timestamps and mismatch, and never pad beyond the solver domain.
- Coordinate frame: the XML/world frame, with the registered histogram origin and cell width from `F3-GATES.json`; persist the exact frame and hashes in each manifest.
- Hard fields: identity uniqueness, finite values, mass conservation, domain/penetration tolerance and known runtime domain.
- Tasks: numerical particle trajectory/state prediction is T1; material arrival and terminal destination are separate T2 labels and must not be conflated.

## Blocking execution issue

Running `l1r_f3_metrics.py` in the current environment was initially blocked by a system NumPy/h5py ABI mismatch. A clean virtual environment with the declared requirements now runs the audit successfully. The registered spatial comparison still fails the screen: plain 0.030 vs 0.015 has TV 0.1407407451 (>0.05); therefore the existing ladder is not a qualified recipe. This is evidence against qualification, not an environment blocker.

## Decision

`formal_v0.1 = NO_GO`; `development tranche = NO_GO`; F3 status remains `candidate-only / qualification pending`. Next executable action is to restore the declared Python environment, run the canary audit on the existing plain repaired case, then generate and execute the 0.0075 and 0.006 plain cases under the reviewer resource guards. Do not claim material or learning closure until those artifacts and gates exist.

## 0.0075 m canary result

The plain `dp=0.0075 m` case was generated and solved on GPU4 with the declared long window (`TimeMax=1.5 s`, `TimePart=0.01 s`). GenCase reported 34,560 fluid and 72,540 fixed particles with zero final wall normals. The solver completed successfully and produced 151 native frames. Conversion to HDF5 completed after fixing the reader's leading-space header handling. The converted trajectory has 34,560 unique particle identities, finite positions, and exact initial/final fluid mass `14.580002 kg` with all particles valid at both endpoints. This is an execution and integrity result only; cross-resolution qualification and material fidelity remain unevaluated.

The first cross-resolution screen is now available: plain `dp=0.010` versus `dp=0.0075` over 151 native frames and the registered histogram frame (`origin=(-0.45,-0.09,0) m`, cell width `0.06 m`) has maximum TV `0.0416288821`, below the diagnostic threshold `0.05`. This supports a candidate numerical T1 interval but does not qualify the full ladder or T2/material tasks.

The `dp=0.006 m` plain run was stopped for resource feasibility after reaching `0.350015 s` in roughly 3.1 observed hours with 174,929 particles. This is recorded as a resource feasibility negative result, not a physical failure. The candidate T1 recipe therefore remains bounded to the executed `0.010/0.0075 m` interval pending an explicitly budgeted finer run.
