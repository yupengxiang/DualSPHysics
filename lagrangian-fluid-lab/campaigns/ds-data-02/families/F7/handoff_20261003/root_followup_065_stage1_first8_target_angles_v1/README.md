# F7 fresh065: first-eight target-angle source chain

This handoff is source-only and disabled. It prepares five new internal target amplitudes for
the first-eight axis while preserving the verified mother geometry and native recipe.

The original mother case is F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_COARSE and its actual target
amplitude is 45.0 degrees, evidenced by the read-only mother owner and prepared source assets
listed in metadata/mother-verification.json. The requested internal list was 35/40/45/55/60
degrees. Since 45 degrees is the verified mother, fresh065 reuses that mother condition and
replaces the duplicate fresh 45 request with 50 degrees. The first eight are 30, 35, 40, 45
(mother reuse), 50, 55, 60, and 65 degrees.

Fresh source cases are F7_OBSTACLE_QUINTIC_B08_A035, A040, A050, A055, and A060.

Only the amplitude scalar changes. The DP 0.02 source Definition, explicit four wet slabs,
finite open-top tank, all-filled type-1 paddle, pivot, Mk/type ordering, controls, 0..8 s two
cycles, 8..12 s rest, 12001 motion rows at 0.001 s, 12 s window, 0.02 s output cadence, and
native mass policy are bound to the mother recipe. Expected native counts are 70179 total,
27495 fixed, 1984 moving type-1, and 40700 fluid type-3. Native fluid mass 325.60001628 kg and
continuum envelope mass 320.1984 kg remain separate; no rescaling is allowed.

The analytic quintic target is described as C2. The native solver reads sampled motion with
piecewise-linear absolute-angle interpolation, so fresh065 makes no native C2 claim. Every fresh
source condition has a source-plan condition hash and a separate canonical physical-binding hash;
their equality is neither expected nor asserted.

Root execution order is: enable motion preparation, then genuine GenCase, run
scripts/bind_first8_receipts.py --mode bind on completed JSON receipts, review the resulting
binding, enable official PartVTK initial QA, and only after a passing five-case QA bind and review
the five disabled 12 s / 601-frame qualification requests. No source handoff grants visual
acceptance, Q-N, production/domain approval, or independent-case credit. The helper reads JSON/XML
metadata only; native BI4/CSV array reads remain inside the Root-enabled QA worker.

All requests in requests/ have launch_allowed=false. This worktree contains no generated motion
table, XML/BI4 output, CSV, H5, solver output, or array evidence.
