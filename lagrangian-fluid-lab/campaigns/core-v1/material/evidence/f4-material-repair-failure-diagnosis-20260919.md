# F4 repair canary failure diagnosis (2026-09-19)

Qualification claim: none. All fractions use the full 512-seed source denominator; the 1% unknown gate is unchanged.

The prior baseline24 dense overlay had 89.6484375% unknown mass. The fixed-k ESS32 candidate has 92.3828125% unknown and the affine-bound candidate has 95.5078125%; both are mass-closed and unavailable for T2 qualification.

The manufactured calibration and the native CFD failure are different mechanisms. Manufactured source failures were ESS-only false alarms: rank, anisotropy, and reconstruction passed, and k=32 removed those false alarms. In the real dense source, both candidates are reliable through frame 80 (.160015 s). At frame 81 (.162004 s), each loses 64 seeds while ESS, rank, anisotropy, and support distance still pass; the estimated reconstruction p95 is about .139/.133 m/s versus the fixed .0469814 m/s cap. At frame 82 the reconstruction failure count is 128. Support-distance failures become material later, from the frame-120 region onward.

Two design-only paths are recorded in the JSON: an independent native-kernel MLS backend bound to the prepared h/Wendland case, and a solver-coupled passive-material implementation using the solver's internal neighbor list and time integrator. Neither path is implemented, launched, or qualified.
