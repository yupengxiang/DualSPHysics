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
