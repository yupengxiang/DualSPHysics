# fresh188: F5 M110/T080 metadata preflight

This package is written in the F3 source worktree for an actual F5 case:
F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T080. The assignment family and the
physical case family are intentionally recorded separately.

The preflight joins the genuine GenCase receipt and prepared report, initial
placement QA, native receipts, typed conversion report, N3 XMF manifest, bed
audit, terminal 801-frame renderer receipt, and atomic publish receipt. It
keeps the native canonical physical scope (873b4e...) separate from the
typed legacy-owner scope (06e5da...), and keeps the independent bed
SourceDef/source-plan role (426b2e...) explicit. The XMF source-H5
association is producer-attested (65a9f7...); this package does not open or
hash the H5.

The render metadata reports 801 frames, 194427 particles, 34 contact sheets,
and key indices 0,100,200,300,400,500,600,700,800. The atomic publish is
terminal and the render report preserves the full time sequence. This package
does not open or hash any PNG and makes no personal visual decision. Personal
review is deferred to fresh189.

Run the read-only validator from this directory:

    python3 -B scripts/validate_fresh188.py

The validator hashes only JSON/XML/XMF/Python/Markdown metadata. H5/BI4/IBI4
/CSV/DAT/VTK references are producer attestations only. The package contains
no scientific payload and starts no job.
