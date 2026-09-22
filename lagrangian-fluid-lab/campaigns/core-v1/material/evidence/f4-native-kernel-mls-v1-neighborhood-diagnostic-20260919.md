# F4 native neighborhood and near-contact diagnostic (2026-09-19)

CPU-only read of native dense source `campaigns/core-v1/runtime/attempts/f4-resting-pool-native-dense-002-canary-s0p3-center-q0p5/20260919T185855-d91665790347/product/trajectory.h5`; source SHA `eaa423cd1e6cdb2e0bd89fcd9b0332fd0e9524e10be0c907926d4155b3ce46b9`; code SHA `69229cf7126afea3ff148a91e8aaa79174f63ad03a0f1160a2323e0d1f2761b2`. No solver, GPU, ledger, or qualification claim.

The `.213 s` value from the old overlay is not first contact: `core_cfd` uses a 5% initial-drop-mass-below-pool proxy. The saved native source has first any-drop crossing at frame 85 / 0.1700054 s.

At frame 81 / 0.1620039 s, the native drop-pool minimum gap is 0.0146 m, below the MLS support radius 2h=0.023883 m; the 5th percentile gap is 0.0150 m. The query overlay has no cross-initial-label supports yet, but the current velocity branch diagnostic reaches p95 separation 0.256 m/s versus within-branch RMS 0.100 m/s and reconstruction residual p95 0.164 m/s.

By frame 82, 12.5% of query supports contain both initial source labels, with p95 branch separation 1.113 m/s and residual p95 0.474 m/s. At frame 85 the source gap minimum is 0.00329 m and mixed-support fraction remains 12.5%; at frame 90 it is 18.0%. These are causal current-neighborhood observations; initial labels are used only for attribution and never to partition the MLS support.

The static numerical reliability mask is 100% in these rows because this backend has no legacy reconstruction-residual gate. That does not establish material reliability or a path-error upper bound.
