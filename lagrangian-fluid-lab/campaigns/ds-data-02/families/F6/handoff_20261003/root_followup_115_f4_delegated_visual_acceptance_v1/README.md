# F6 fresh115: delegated visual review of two F4 Root638 cases

This package is source-only review metadata in the isolated F6 worktree. It covers exactly:

- F4_DROP gap0.24, x offset +0.08, y offset -0.04, uz 0.4
- F4_DROP gap0.24, x offset +0.08, y offset -0.04, uz 0.6

Both cases are selected from the actual Root638 24-case inventory and have completed/0 GenCase, basic initial QA, native frame-0 QA, full 1201 native, typed conversion, XMF, and render receipts. For each case this review personally inspected all 51 contact sheets and the nine key frames 0, 150, 300, 400, 600, 750, 900, 1050, and 1200 with view_image. PNG SHA256 values are recorded after inspection.

The visual decision is visual-approved-by-delegated-agent. The PNG title still says VISUAL REVIEW PENDING ROOT and PRECISION NOT ACCEPTED; that stale title is retained as a limitation. This package does not grant global case credit, Q-N, Q-E, numerical precision, convergence, production approval, or root-personal image inspection.

The .4 producer conversion report records 55 transient missing-frame events and 140 type/mk frame events, while .6 records zero. These are lifecycle event metrics. The package leaves maximum_missing_particles_per_frame null because the producer does not supply that independently bounded field, and it does not infer final UID survival from images.

Scope values are kept separate: actual converter physical scope and manifest consumer binding, actual owner-file declared scope, source-owner declared scope, and source-plan scope. The actual converter/manifest hash is not declared equal to the owner-file/source hash or source-plan hash. Scientific payloads H5, BI4, CSV, VTK, and DAT were not read, copied, or hashed by this review; producer-attested digests are retained only as metadata.

Validate with:

    python3 workers/validate_fresh115.py
