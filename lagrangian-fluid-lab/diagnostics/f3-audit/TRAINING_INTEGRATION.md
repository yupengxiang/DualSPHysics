# F3 training integration checkpoint — 2026-09-12

No real training or independent development CFD has run. Engineering reader and rollout checks do not qualify a dataset or trained model.

The F3 adapter has 48 base features (56 with the actual eight-neighbour summary). The declared rollout predicts displacement divided by U*dt; initial velocity is native, then recurrent velocity is preceding displacement/dt. The old cup trainer expects115 base features, next-velocity targets, a capped output and trapezoidal position integration. Reuse its model classes only until a dedicated F3 trainer is implemented. Do not use its future-survivor filtering or validation aggregation that omits failed cases.

Native NP01 has836 frames ending at8.350023745969017s. Prescribed control ends at8.35s. A qualified uniform0–8.35s time schedule must be explicitly established by the finer-output comparison. Using every native interval would exceed control coverage; silently extending control or deleting the final interval is invalid. True targets remain separate from current/past model inputs.

The qualified loader must verify recipe/time/output/domain evidence, every actual development trajectory audit and file hash, fixed forcing and physical lineage, and the registered public-development split.32 CSV candidates are input definitions only. Qualification NP01 and other reference cases are not development cases. Use the registered8-case pilot before expanding actual independent data.

Checkpointing must save model, AdamW state, RNG including NumPy Generator state, exact transition order/cursor, global step, phase/epoch, best-model and early-stop state, and all effective configuration/data/code hashes. Atomic saving plus a fresh-process continuation comparison is required; a metadata schema or state_dict alone does not prove recovery. Every execution, including failed attempts and restart, consumes a training attempt.2 pilots plus6 finals use8/12 before recovery attempts.

Autonomous evaluation keeps failed cases in the denominator and preserves unmodified finite predictions for wall checks. No clipping, projection, particle filtering or failure-only survivor ranking. GPU/end-to-end costs include neighbourhood computation and evaluation.

The current blocked-distance local summary bounds memory but remains quadratic. At14580 particles,835 rollout steps require about1.775e11 distance pairs; at34560, about9.973e11. These are operation counts, not measured runtime. Any spatial-index replacement must preserve exact neighbourhood/self/tie/feature semantics; sampling target particles must retain the full current context. The legacy final neighbour-fraction feature depends on the full target set.

Reviewed engineering files: scripts/f3_frame_reader.py, scripts/f3_rollout.py, scripts/f3_learning_inputs.py. Dedicated qualification scoring and training-launch accounting infrastructure are in progress; a production training driver is still required.

Prospective neighbour repair: F3-LOCAL-IDENTITY-REPAIR.json records10/128 sampled float32 self-exclusion failures in the historical routine. The active F3 rollout now uses scripts/f3_local_neighbors.py: explicit integer-ID exclusion, float64 exact spatial search, complete kth-distance shell and distance/ID tie ordering. Coincident distinct IDs are retained. This is a declared new feature contract, not bitwise legacy equivalence.13 neighbour/rollout tests passed; full14580-particle initial summary took0.285s on one CPU thread, with128 dense-oracle rows verified and zero self IDs. No GPU/training performance claim. Future trainer must use this same current-state summary.

The same identity-v2 algorithm now vectorizes rows with unique cutoff distances and expands full shells only for ambiguous ties. F3-LOCAL-IDENTITY-OPTIMIZATION.json binds the final code: full14580-particle summaries measured0.149s at the initial lattice and0.0484s at native frame400 on one CPU thread;128 dense-oracle rows passed in each. These remain engineering state computations, not model timings.
