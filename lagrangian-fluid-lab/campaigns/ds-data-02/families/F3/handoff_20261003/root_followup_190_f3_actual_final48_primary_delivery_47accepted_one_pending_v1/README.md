# F3 fresh190 actual final48 primary delivery

This package is a metadata-only assembly of the F3 delivery frontier at
checkpoint 317.  It records 47 cases with an accepted visual decision and one
registered case that is still pending its own visual decision.  It does not
claim that the final48 delivery is complete.

The 39 inherited rows remain references to the immutable Root1328 primary
catalog.  The eight later accepted rows are assembled from their own
checkpoint-317 accepted decisions, own full836 QI records, and explicitly
named native, typed, XMF, render, publish, parent-QA, and source-preparation
evidence.  The join key is each row's `physical_case_id`; case aliases are
retained in their source evidence.  The frozen first8, actual first24, and
registered final48 arrays are copied from the authoritative Root1276/Root1328
membership records and are not reselected from the current accepted count.

The pending row is `F3_STAGE1_DP006_P1200_AY0390` /
`F3_TWOAXIS_P1200_AY0390_STAGE1_FIRST48_PITCH_VARIANT`.  Its registered
pipeline observations are retained as readiness metadata only.  It has no
accepted decision, primary particle/XMF/render references, personal visual
review, or credit in this package.

Role boundaries are preserved per case.  Native canonical condition,
converter/typed legacy scope, XMF condition and physical-plan fields, source
plan fields, and render/bed/source-definition roles are recorded as present or
absent from their own producer metadata.  The shared two-axis initial QA is
not relabeled as an independent case QA.  The AY0270 row keeps the original
typed154 unknown runtime boundary separate from the completed artifact audit
and recovery-XMF evidence.  Historical native runtime unknowns and missing
physical identifiers remain unknown.

Contact and key PNG references are producer references.  This source package
checks their existence and records file size, but does not open or hash PNG
bytes.  It also reads and hashes JSON metadata only; scientific H5, BI4,
IBI4, CSV, DAT, VTK, and related payloads are neither opened nor hashed.
No solver, conversion, render, or shared-ledger action is performed, and the
package grants zero case credit, visual credit, Q-N, or Q-E.  Numerical
precision and strict physical claims remain outside this delivery assembly.

Run the read-only validator from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B validate_fresh190.py
```

The validator requires the frozen checkpoint/index and Root1328 catalog to
remain byte-addressable, verifies the 47/1 boundary and membership subsets,
checks JSON reference identities and terminal receipt roles, stat-checks
published PNG/XML/XMF references, and rejects scientific-payload paths.
