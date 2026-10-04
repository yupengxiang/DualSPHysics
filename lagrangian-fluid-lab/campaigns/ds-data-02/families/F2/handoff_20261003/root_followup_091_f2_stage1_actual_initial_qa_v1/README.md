# F2 Stage1 fresh091 actual initial QA bindings

This package binds the two Root101 GenCase receipts to disabled CPU PartVTK
frame-zero QA requests:

- `F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010`
- `F2_STAGE1_OFFSET_P03_DP010_SPATIAL_REFERENCE_SAVE010`

Root101 is the only GenCase evidence consumed here. Each receipt is
`completed` with return code `0`, dimension `3`, and its own generated XML,
BI4, report, and dynamic particle counts. The earlier Root100 source/failure
attempts remain historical evidence and are not substituted.

`workers/f2_stage1_initial_qa_worker_v2.py` reuses the reviewed PartVTK
invocation but reports counts from the actual receipt/XML and derives UID/type/Mk
partitions and unscaled mass sums from the actual frame-zero CSV. It does not
assume the accepted mother's 24,576-fluid count, normalize mass, retain arrays,
start GenCase, or start DualSPHysics. The two requests remain disabled until
Root enables them through the shared runner.

Run `build_f2_stage1_actual_qa.py` only to regenerate the metadata bindings and
disabled requests after Root supplies a replacement completed receipt. This
source package itself does not run PartVTK.
