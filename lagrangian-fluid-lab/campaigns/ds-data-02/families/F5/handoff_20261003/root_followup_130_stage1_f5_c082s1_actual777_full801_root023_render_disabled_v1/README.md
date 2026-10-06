# F5 fresh130: actual Root777/778 -> disabled Root023 render

This package is source-only and lives in the isolated F5 worktree. It binds the two actual Root777 N3 XMF products and the two actual Root778 full-event bed reports to disabled Root023 render requests. No solver, renderer, converter, shared registry, or scientific payload was started or read by source preparation.

Root778 completed both 801-frame reports. Each endpoint has 801 frame rows, 194427 native particles, and a 31658 Type-3 initial-fluid UID denominator. The metadata report gives zero 1DP and 2DP penetration counts and fractions on every frame, zero missing/unexpected UIDs, zero nonfinite position/mass rows, zero x/y footprint exclusions, and 31658 current valid/evaluable fluid rows on every frame. These are diagnostic report values. The worker status remains `completed_worker_output_pending_root_review`; exit code 0 is not physics acceptance. Root023 rendering and manual visual review remain required, and `full801_authorized`, Q-N, and case credit remain false.

The requests use Root142 CPU `audit`, 24 reserved CPU threads with all renderer environment caps at 2, a 14400 s wall limit, and a shared render cap of 2. They preserve actual native/XMF/bed producer hashes. H5 is present only as a producer-attested input digest; the package does not open or rehash it. Canonical physical scope and legacy H5 scope remain separate. Future render receipt/manifest/frame hashes are null.

## Root entry points

- `requests/M085_T080-full801-root023-render-request.json`
- `requests/M115_T100-full801-root023-render-request.json`
- `scripts/validate_fresh130.py` (metadata/static-input validator; report excluded from manifest)

The original A/B dynamic penetration failures and the exact DP lattice precision negative (5.0000000158e-6 cells versus 1e-6) remain historical evidence and are not changed by this package.
