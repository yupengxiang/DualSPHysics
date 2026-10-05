# F2 fresh098 — actual typed401 to disabled XMF/render bindings

This source-only package binds the four Root294 typed attempts whose JSON receipts/report metadata say `completed`/returncode `0`, 401 frames, 418104 particles, solver dimension 3, and PartVTK `all_passed=true`: RX047, RX050, RX055, and RX060. RX063 remains running and is recorded as excluded in `metadata/case-registry.json`.

The package reads JSON/XML metadata only. It does not read or hash BI4, H5, CSV, or scientific arrays. Each conversion report's producer `output_sha256` is carried as the trajectory H5 digest; it is not recomputed here. The report's `legacy-owner-scope.v0` physical hash and the source-plan hash remain separate.

Each case has an actual typed binding, a disabled N3 XMF request, and a disabled Root023 full401 render request. Both disabled CPU requests contain explicit `estimated_storage_bytes` (32 GiB), `worktree_root`, `strict_guard`, `strict_guard_digest`, literal input-file closure, and an empty child output-directory contract (`{attempt_root}/xdmf` or `{attempt_root}/render`). Future XMF/render product hashes stay null. Root must enable them through the shared runner after review.

Native counts are 418104 total / 372840 fixed / 24150 moving / 0 floating / 21114 fluid in 3D. Native fluid mass 21.114 kg and continuum fluid mass 18.876 kg are both retained without rescaling.
