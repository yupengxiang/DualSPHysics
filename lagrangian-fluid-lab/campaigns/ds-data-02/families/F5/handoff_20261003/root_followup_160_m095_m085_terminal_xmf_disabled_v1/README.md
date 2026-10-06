# fresh160 — terminal M095/M085 XMF bindings (disabled)

This F5-only package binds the already terminal Root939 M095_T080 and Root854 M085_T100 typed producer metadata to two disabled N3 temporal XMF requests. Both producer receipts are `completed` with return code 0, and both conversion reports attest 801 frames, 194427 particles and 3-D output. The M095 `trajectory.h5` filesystem observation records only `stat` metadata; no source code in this package opens or hashes H5. The producer H5 digests are copied from each conversion report's `output_sha256`.

The XMF worker consumes the aliases `typed_receipt`, `native_receipt`, `conversion_report` and `trajectory_h5`; each binding explicitly sets `native_receipt` and `native_receipt_sha256` equal to the existing `full_native_receipt` aliases. Canonical physical scope, source-plan scope, and producer legacy H5/report scope remain separate. The XMF, full-frame bed audit, render, visual review, Q-N and case credit gates remain disabled. Root must materialize a distinct enabled request through Root142 after reviewing the metadata.

Run the metadata-only validator with `python3 scripts/validate_fresh160.py`. It refuses science-suffix hashes, checks the terminal JSON contracts and input closure, and verifies the H5 observation only with `stat`; it never opens the H5.
