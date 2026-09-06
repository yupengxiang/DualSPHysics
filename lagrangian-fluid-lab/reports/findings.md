# Exploratory run findings

The end-to-end pipeline produced **30 normalized probes**: **29 passed** the current exploratory quality gates and **1 failed** them.

A solver return code is deliberately not treated as proof of dataset quality. Each case must also reach its target time, satisfy HDF5 structural checks, keep density within a broad sanity range, and obey lifecycle rules appropriate to its boundary model.

## Quality failures

- `O5_wave_runup`: closed-domain identity retention is only 0.001; excluded-particle fraction is 0.999

## Semantics established

- Closed, fixed-resolution cases can use stable `Idp` trajectories; shifting is disabled in the custom probes.
- Open boundaries need birth/death masks. The impinging-jet probe injects new IDs, so a fixed conserved particle set is invalid.
- Variable resolution needs `(Zone, Idp)` to identify exported numerical nodes. Split/merge continuity requires a separate lineage representation.
- Floating-body boundary particles are preserved with `Type=2` and can be tracked alongside `Type=3` fluid particles.

## Most important resolution result

The coarse wave-runup probe (`dp=0.04 m`) completed normally but lost 21,695 of 21,723 initial fluid identities. The refined probe (`dp=0.025 m`) retained essentially all particles (one exclusion). This is the clearest proof that workflow smoke tests and scientifically usable dataset runs must be reported separately.

## Scope warning

These are mechanism and plumbing probes, not converged CFD benchmarks. They establish installation, case generation, multi-GPU scheduling, raw-output retention, trajectory normalization, and failure detection. Resolution studies, validation against experiments, nondimensional coverage, and train/validation/test split design remain future work.
