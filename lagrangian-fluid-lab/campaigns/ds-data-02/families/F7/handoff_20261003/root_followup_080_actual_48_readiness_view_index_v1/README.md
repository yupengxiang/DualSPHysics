# F7 fresh080 actual 48-case readiness and viewing index

This package is a metadata-only snapshot for the 48 physical F7 identities
registered by immutable fresh079 (`de5e2d42`). It keeps the historical fresh062
mother identity separate from the 47 fresh064/065/070/074 source rows and keeps
the excluded A052P5 prospective condition out of the family count.

`metadata/family48-readiness-index.json` records, per case and per stage,
the selected GenCase, initial QA, native, typed, XMF, and renderer receipt
paths. Each receipt entry carries the observed status, return code, UTC start
and finish times where present, request SHA, expected frame/particle/count
metadata, and physical/source-plan scope fields. Typed conversion reports and
XMF manifests contribute bounded frame, particle, dimension, count, and first/
last time metadata. The selected historical mother native input is the
completed restored-motion retry 025; its failed verified-recipe attempt 023 is
retained under `historical_alternate_attempts`.

`metadata/render-view-index.json` is the Root viewing handoff. A completed
renderer report lists its 26 contact-sheet paths and six key-frame paths
(saved frames 0, 120, 240, 360, 480, and 600). The index does not open image
payloads and leaves visual review pending for Root. Renderer report and XMF
metadata digests are present only for completed metadata outputs; every
unfinished stage has a null completed-output digest. Scientific BI4, H5, CSV,
and DAT hashes are intentionally omitted.

The `render_controller` block and `stage_counts` in the JSON are the
authoritative snapshot of the Root413/414 P5 queue (the parent handoff reported
live session 96407). Re-run the builder after Root advances the live queue to
refresh the snapshot; it never launches work or edits consumed source
packages.

The bounded builder is
`scripts/build_fresh080_readiness_index.py`. Its inputs are the F7 DATA tree,
the immutable fresh079 audit, and the integration handoff tree. It uses only
stdlib JSON/path metadata operations and refuses scientific payload suffixes.

No visual acceptance, Q-N qualification, numerical precision, production
approval, or independent-case credit is granted by this package.
