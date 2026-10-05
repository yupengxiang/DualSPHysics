# F4 fresh088 individual GenCase receipt binder

This is a source-only handoff for the six lattice-aligned F4 fallback cases
from fresh087. Root runs the six genuine GenCase requests separately. After
those requests finish, this package can bind the six individual
`execution-receipt.json` files, generated XML files, and BI4 paths into the
fresh087 native-QA worker contract.

The binder is deliberately conservative:

* it derives each output prefix from the actual fresh087 request command and
  the actual individual runtime output root;
* it accepts only a completed per-case runtime receipt with returncode 0;
* it parses the generated XML for actual total/fixed/fluid counts and checks
  the source UID partition without opening BI4;
* it accepts a BI4 SHA only from a Root-registered producer binding. It never
  hashes BI4, H5, VTK, CSV, or other scientific arrays;
* it preserves the old Root195-style aggregate failure as provenance and never
  promotes an aggregate receipt to a completed parent.

Root227 has now registered the six outputs in
`root_stage1_f4_six_lattice_aligned_genuine_gencase_227/root-source-review-and-request-index.json`.
The helper consumes that index directly. Each row points to the prepared
prefix, whose sibling `prepared-input-report.json` is the registered producer
for the XML and BI4 digests. The helper still refuses to hash BI4; it records
the producer's `bi4_sha256` and checks only the BI4 file's nonzero size.

`requests/bind-individual-gencase.request.json` is the disabled metadata-only
CPU request for this helper. It includes the six small reports, receipts, and
XML files as provenance inputs and leaves BI4 files deferred with null hashes.
Its output is the exact binding path consumed by
`requests/root227-six-case-native-qa.request.json`:

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F4/F4_FALLBACK6_LATTICE_DP010_BINDING/root-stage1-f4-fallback6-individual-gencase-bind-088/individual-gencase-binding.json`

## Source checks delivered here

`workers/verify_f4_consumer_schema_v1.py` checks all six fresh087 GenCase,
initial-QA, and qualification request objects using only JSON and file
metadata. It does not read generated outputs or scientific arrays.

That check records a consumer detail which matters for launch: the six
fresh087 initial-QA request filenames are per-case, but
`run_f4_fallback_native_initial_qa_v1.py` is an aggregate six-case worker and
rejects a one-row binding. Root should run the single disabled aggregate QA
request in this package after the binder completes. The output binding uses
the existing worker's exact `generated_bi4: {path, producer_sha256,
content_rehashed_by_source: false}` shape; no hidden wrapper key is added.

The source-only verification ran the binder against the registered Root227
index and then called the fresh087 worker's binding parser only. It accepted
all six rows and did not start the official BI4 audit. The later aggregate QA
request is the first step that is allowed to open scientific initial-state
arrays.

`workers/check_f4_mother_diff_v1.py` independently verifies each committed
Definition against the frozen fresh087 mother hash. It proves the one allowed
drop-point-z replacement and reports all other bytes unchanged. The committed
`evidence/mother-diff-evidence.json` is source evidence only; it is not a
GenCase or QA result.

Root216 remains negative evidence. Its aggregate native QA had returncode 1
and failed the source-population checks; none of its BI4 or hashes is reused
by this package.

No GenCase, native QA, solver, converter, array read, registry write, or
shared-ledger write was performed while preparing this package.
