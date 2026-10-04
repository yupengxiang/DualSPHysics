# F2 frame-zero wall support and saved-frames 0..50 audit (fresh058)

This scope prepares a Root-strict, source-only audit for the existing
`F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010` typed
trajectory.  It is disabled in this handoff and does not launch a worker,
solver, conversion, GenCase step, or renderer.

If Root enables the request later, the worker reads the existing H5 read-only in
chunks.  At frame zero it visits every particle and retains summaries for all
valid finite native type-3 fluid coordinates and all valid finite native type-0
fixed plus type-1 moving boundary coordinates.  It builds a `scipy.spatial`
`cKDTree` over that complete type-0/type-1 candidate boundary pool and queries
all frame-zero type-3 fluid coordinates in chunks.  The receipt reports distance
minima and percentiles, nearest sample UIDs, per-boundary-type counts, and the
declared cup-envelope source.  It never writes those coordinate arrays.

For saved frames 0 through 50 inclusive, the worker visits all valid finite
type-3 fluid rows and reports velocity-squared (`v^2`) statistics, maximum and
percentiles, unweighted COM, coordinate envelope, valid active count, and the
missing count relative to the frozen initial fluid denominator of 24,576.  It
also reports descriptive near-cup-wall versus interior bins using the declared
cup envelope and the nominal three-layer span (`3*dp = 0.03 m`).  Those bins
overlay the full valid type-3 summaries; they are not a particle-removal mask,
mass rescale, or precision/acceptance gate.  Frame-zero native KDTree distance
is kept separate from the static declared-envelope descriptor for later frames.

The bound source defines cup low `(0,-0.15,0.65) m`, size
`(0.425,0.30,0.45) m`, coarse `dp=0.01 m`, and continuous fluid
`(0.0525,-0.12,0.70)` to `(0.3725,0.12,1.02) m`.  Existing initial QA reports
positive fluid-solid separation and no fluid point in the declared cup,
receiver, or tray envelopes.  The existing typed metadata retains zero missing
fluid identities at frames 0, 25, and 50 and a terminal maximum of 118 missing
identities.  These facts remain descriptive source evidence; this scope makes
no explosion, invalid-state, hydrostatic-causality, Q-I, Q-N, production, or
visual-acceptance claim.

This turn inspected metadata, source/current XML, existing QA, conversion and
animation receipts, and prior source handoff files only.  It did not open the
trajectory H5, native BI4, CSV, image, or raw particle arrays.
