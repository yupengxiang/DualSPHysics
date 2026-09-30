# F1 DS-DATA-02 handoff

Status: definition ready; shared CPU GenCase reservation and runner execution are pending.

The official v5.4 mothers were read from the historical read-only lab and are
bound in `source_audit.json`.  The successful records are actual 3-D canaries:

- `main/01_DamBreak`: Dp 0.020 m, 9,600 fluid + 7,846 fixed particles,
  1.60 x 0.67 x 0.40 m tank, nominal 0.40 x 0.67 x 0.30 m initial fill;
  the realised initial particle bounds are 0.03..0.41 x 0.03..0.65 x
  0.03..0.31 m, DBC.
- `mdbc/04_Dambreak`: Dp 0.020 m, 79,380 fluid + 93,042 fixed particles,
  3.22 x 1.00 x 1.00 m tank, nominal right-side fill about 1.228 x 1.00 x
  0.55 m; realised initial particle bounds are 2.02..3.20 x 0.02..0.98 x
  0.02..0.54 m, mDBC.

The historical 0.6 s runs have seven frames and are canary evidence only.  The
reference matrix therefore binds 1.6 s for the eccentric obstacle and 6.0 s for
the dual-channel event, with the mother save cadence of 0.01 s.  It contains
two backgrounds at coarse/medium/fine Dp values chosen from local feature
scales; Dp is not a metadata-only label.  The dual initial fillbox starts
0.108 m upstream of the separator end and extends 0.172 m beyond the finite
right wall, matching the official mDBC flood-fill pattern; ending at either
interface is a GenCase zero-fluid failure even with return code 0.

`case_registry.jsonl` has 48 candidate physical cases (24 per background).
They are pre-registrations: no row claims a solver attempt, HDF5, labels,
preview, Q-I, Q-N, or production status.  `integration_save_plan.json` keeps
the sensitive dual-channel medium case for separate native-dt, half-dt, and
save-cadence checks.  The starting engineering budgets are 5% for macro
observables and 2% of sqrt(H0/g) for event times; they are not universal SPH
tolerances.  The 0.01 s matrix output is raw macro reference only; event-time
qualification requires a complete-window 0.001 s control (worst-case snapshot
quantisation 0.0005 s) and a recorded half-native-dt integration comparison.

Next executable task: obtain the shared CPU reservation, run GenCase only for
the six definitions, bind actual generated XML and particle counts, then submit
the six solver jobs through the shared runner.  This worktree never starts a
GPU or solver process.
