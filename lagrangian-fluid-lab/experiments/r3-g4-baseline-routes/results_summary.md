# R3 G4 candidate route results

Status: complete, candidate-only diagnostic.  The run finished six jobs
(LocalInteraction/PhysicsResidual × seeds 17, 29, 43) using the shared
release manifest and corrected trainer.  Each job was limited to three
requested epochs, `max_particles=64`, `validation_particles=96`, and hidden
width 32.  The launcher assigned only physical GPUs 4 and 5, one at a time;
the per-job UUID, driver, memory snapshot, command, and log are in
`run_manifest.json`.

The pre-existing sidecar-aware matrix was not retrained: the independent
contract audit found all four routes (Particle MLP, DeepSets, LocalInteraction,
PhysicsResidual) with complete 3-seed coverage (12/12), common 43-wide inputs,
10-wide controls, 3-wide static physics, and 7-wide current boundary summaries.

## Independent small rerun

Values below are test-case vector RMSE divided by particle spacing (`dp`).
They are included to expose route behavior under the small budget, not to
establish a ranking or a physical-scene gate.

| route | seed | epochs run | F1 twin obstacle | W06 fast center | F3 transverse slosh | per-seed macro mean |
|---|---:|---:|---:|---:|---:|---:|
| LocalInteraction | 17 | 3 | 2.9686 | 114.1817 | 1.9706 | 39.7070 |
| LocalInteraction | 29 | 3 | 3.3447 | 124.0578 | 2.0308 | 43.1444 |
| LocalInteraction | 43 | 2 | 2.7148 | 136.9292 | 1.7459 | 47.1299 |
| PhysicsResidual | 17 | 3 | 2.7968 | 30.0410 | 3.4214 | 12.0864 |
| PhysicsResidual | 29 | 3 | 3.5172 | 21.6994 | 4.9959 | 10.0709 |
| PhysicsResidual | 43 | 3 | 2.8311 | 21.0363 | 3.4120 | 9.0931 |

Across seeds, the case means (sample standard deviation) were:

| route | F1 twin obstacle | W06 fast center | F3 transverse slosh | macro mean across seed macro means |
|---|---:|---:|---:|---:|
| LocalInteraction | 3.0093 (0.3169) | 125.0563 (11.4065) | 1.9158 (0.1502) | 43.3271 (3.7149) |
| PhysicsResidual | 3.0484 (0.4064) | 24.2589 (5.0184) | 3.9431 (0.9118) | 10.4168 (1.5263) |

All six test rollouts completed and reported finite metrics.  The W06 fast
center values are unstable under this tiny budget and should not be
interpreted as a route conclusion.  The run has no material-transport,
density/pressure-prediction, free-body-coupling, T2/T3/T4, wall-contact, or
formal acceptance evidence; hard clipping was disabled (`clip_dp=0`) and the
trainer's smooth output cap remains disclosed in each result JSON.
