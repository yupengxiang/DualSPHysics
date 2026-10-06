# F5 fresh190 membership audit

This source-only package reconciles three distinct membership notions for F5 C082S1: the accepted `first8_visual_subset_56` from source178, the eight parent conditions used by fresh117, and the 24-condition fresh117 source batch, against the fresh169/current48 physical membership and checkpoint185 accepted metadata.

Membership uses the pair `(physical_case_id, canonical physical-condition SHA256)`. A shared generic `case_id`, directory alias, or stage snapshot does not establish identity. The package records source-definition (SourceDef), source-plan, canonical-owner, actual converter legacy, native-canonical, and XMF roles separately. Missing native/XMF aliases remain explicit nulls; no hash is copied between roles.

The computed relations are: first8 visual versus current48: 8/8; fresh117 parent set versus current48: 2/8; fresh117 first24 versus current48: 14/24; current48 categories: {'endpoint': 2, 'mother_full801': 12, 'next34': 34}. The six fresh110 parent keys and four fresh117 T120 keys outside current48 are retained as a membership discrepancy.

The latest checkpoint185 metadata reports F5 accepted count 11 at checkpoint total 269. This package does not change credit, grant Q-N, start jobs, or authorize later stages. Fresh169 stage values are status-only historical snapshots.

No BI4/H5/CSV/DAT/VTK/PNG scientific payload was read or hashed by this source preparation. Only JSON/Markdown metadata and this validator are included.
