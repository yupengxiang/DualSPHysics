# F5 family handoff

F5 is a fresh DS-DATA-02 3-D wave/run-up family.  The historical official WaveRunup and R3 16 s/801-frame runs were audited as candidate-only evidence.  Their generated XML/BI4/HDF5 and trajectory data are not reused as native inputs; the formal reuse count is zero.

The `runup_return` background uses a finite-width tank with a closed continuous bed profile that rises from the upstream floor to a crest and descends into a downstream return region.  The `weir_pair` background keeps the same bed, source and piston control but adds a finite two-segment transverse weir.  The segments leave a 0.25 m lateral slot, so sidewise transport is an explicit geometry event.  Alternating pre-registered crest states define paired overtopping and no-overtopping targets.

The piston control is copied from the official 17_WaveRunup motion source on a 0.025 s grid through 15.6 s and held at zero through the 16 s window.  A single-packet control template is frozen as a control holdout.  The reference ladder is dp=0.030/0.025/0.020 m; all matrix rows use TimeMax=16 s and TimeOut=0.02 s.  Thresholds, event crossings, initial-mass denominator, unknown handling, and independent integral/save controls were written before any native result.

The registry has 48 independent physical cases, pair-preserving splits train=24, validation=6, ID test=6, parameter-OOD=6 and geometry/control-OOD=6.  Resolution, integration, save and preview views do not add cases.

No solver, GPU or native labels were launched by this family.  The next executable task is to submit the two bounded CPU GenCase requests through the shared runtime, then bind actual 3-D particle/mass/side-layer/boundary/control evidence before registering qualification requests.
