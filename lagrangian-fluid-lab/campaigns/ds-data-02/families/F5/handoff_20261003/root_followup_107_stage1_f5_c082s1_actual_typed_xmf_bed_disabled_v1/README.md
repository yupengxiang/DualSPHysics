# F5 fresh107: actual Root486/487 typed -> disabled XMF and bed audit

This is a source-only handoff for the two already completed Root486/487 short typed conversions. It does not launch a task and does not read or hash H5, BI4, CSV, VTK, or DAT payloads.

## Actual upstream evidence

- **A080**: native Root455 `root-stage1-f5-c082s1-A080-short-native-qualification-104-root455` and typed Root486 `root-stage1-f5-c082s1-A080-short-native-typed-nvme-105-root486` are producer metadata with completed/0 receipts.
  - typed conversion report: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-A080-short-native-typed-nvme-105-root486/typed/conversion-report.json` (builder SHA `b8dbd1ac42b5163afa95bae97bacbed7eb9fb53047a9a9bcf5be655633f3cdca`); 51 frames, N=194427, dimension=3.
  - producer-declared H5 SHA: `da915de920078f02fd3305adbf60e8b6a9e5cbbb743842652e4271b4bb6086f0`; source preparation did not open or rehash H5.
  - H5 legacy scope: `f5f261b3e967b92bda5a8367b8fdf2ee841c42c92ee78b36296a65ce8fceb226` / `legacy-owner-scope.v0`; canonical owner remains `68b99ef9d44f0c3a5a999982c3accd8bfc3f31f03af79896cbc4b9c414919b9e` and source plan remains `57d5ea09b1f77cef821ffb7d59e61d0de29444590dc9b9e9b8df0cfcfc2abe5b`.
  - Root455 placement evidence has six positive central Mk50 support bins `[208, 27, 22, 15, 20, 20]`; exact DP lattice 1e-6 negative remains an independent diagnostic.
- **A120**: native Root455 `root-stage1-f5-c082s1-A120-short-native-qualification-104-root455` and typed Root486 `root-stage1-f5-c082s1-A120-short-native-typed-nvme-105-root486` are producer metadata with completed/0 receipts.
  - typed conversion report: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-A120-short-native-typed-nvme-105-root486/typed/conversion-report.json` (builder SHA `da9a278bb2d0346a154200d81111997685b32d95b6c3b93fd15860007a8f2046`); 51 frames, N=194427, dimension=3.
  - producer-declared H5 SHA: `ad27316c5c1ecaef3134ecef05d71c0189aeb4bcf50ed860285a4346b83ad677`; source preparation did not open or rehash H5.
  - H5 legacy scope: `978828e3684e6d68d8e3f8e5955290aacea319e6557add8f2aea5125ab1f439e` / `legacy-owner-scope.v0`; canonical owner remains `6d02cb6e30b62cb881b372f61b6458919544a33ce8a6cfcd5367aab9c1d366a5` and source plan remains `d6939fe3ede9b25b7267d31c03533b2b4f159c70cd197180f4808a77b208fccd`.
  - Root455 placement evidence has six positive central Mk50 support bins `[208, 27, 22, 15, 20, 20]`; exact DP lattice 1e-6 negative remains an independent diagnostic.

## Disabled downstream stages

`requests/*-xmf-request.json` and `requests/*-bed-audit-request.json` are complete runtime-shaped CPU requests with `disabled=true`, `launch=false`, `execution_allowed=false`, `full801_authorized=false`, `q_n_granted=false`, and no case credit. XMF is an N=3 51-frame derived view. The bed worker scans every actual frame, retains the frame-zero Type-3 UID denominator, reports 1DP/2DP counts/fractions/depths, missing/nonfinite UID observations, and keeps the native Mk50/source mkbound40 mapping. Thresholds are diagnostic only.

The bed request remains disabled until Root has a completed XMF producer and binds its manifest/XML through `scripts/bind_bed_after_xmf.py`. The source package does not infer dynamic acceptance from initial placement, typed conversion, or Root visual review. Full801/Q-N/case credit remain on hold.

The XMF and bed bindings preserve canonical physical owner, source plan, and producer H5 legacy scope as separate identities. No cross-resolution equality is asserted. `future_output_hashes` are null in the disabled requests; any actual XMF/bed receipt and output hashes must be filled by Root after execution.

## Source boundary

Worker hashes: `{"bed_worker_A080_sha256": "c81626ab3baa4965aff03c82b2dd8a7711f37ae5e773e6ce7f62cd930d088f48", "bed_worker_A120_sha256": "05905b64519d701b9becf8e21c1738082788f559e00a0d491c6a549de8ddce74", "xmf_worker_sha256": "aeccc3204d751250bd94ffab704ed65c2c691c4739f4b2f5e0d51aefb21b4e3c"}`.
Historical exact-DP lattice negative evidence is retained and is not relaxed or silently promoted to a stage gate. These short 0..1 s diagnostics remain right-censored and do not add an independent case.
