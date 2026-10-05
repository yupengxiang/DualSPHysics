# F5 fresh103: disabled typed/XMF/bed chain for A080/A120

This package is a source-only successor to immutable fresh102. Fresh102 has
five disabled stages and its bed request stops at the short native attempt; it
does not contain a typed converter request or an XMF producer request. Fresh103
adds two disabled CPU stages per candidate and changes the new bed request to
depend on XMF:

motion transform -> genuine GenCase -> initial QA/Mk50 -> short native 1 s/51
frames -> typed NVME conversion -> legacy-aware XMF -> framewise bed audit.

The two physical scopes remain separate:

- A080: 68b99ef9d44f0c3a5a999982c3accd8bfc3f31f03af79896cbc4b9c414919b9e
- A120: 6d02cb6e30b62cb881b372f61b6458919544a33ce8a6cfcd5367aab9c1d366a5

All A080/A120 future particle counts, H5/XMF/audit hashes and receipts are
null or Root binding placeholders. The historical typed317/XMF318 values in
metadata/historical-typed317-xmf318-producer-shape.json describe the real
producer schema only; they are not expected results for either candidate.
The actual Root426 GenCase receipts and prepared reports are recorded separately
as producer metadata and must feed Root's next initial QA binding without
copying their counts into future request expectations.

requests/*-typed-conversion-request.json uses the actual converter contract:
the report solver_dimension is an evidence object, not a scalar; counts come
from actual GenCase/prepared/placement/conversion producers; native weights are
reported without rescaling; source H5 is read-only; and NVME concurrency is 2
with a 24 GiB staging cap and 100 GiB free-space floor.

requests/*-xmf-request.json calls Root's previously verified
export_xmf_legacy_aware.py. Its binding keeps the candidate canonical physical
owner separate from the producer H5 legacy scope. XMF is a derived view and
does not add a case.

workers/bed_audit_candidate.py keeps the fresh096 framewise algorithm but
takes candidate identity/count/profile from the Root-bound JSON binding. The
source profile, source mkbound40, native Mk50, 1DP/2DP bins (0.02/0.04 m),
all-51-frame scan, UID denominator, finite/lost reporting and no-acceptance
boundary are unchanged. It cannot run until Root fills all producer metadata
placeholders.

The initial QA request uses workers/initial_placement_mk50_audit.py. It binds
the actual GenCase receipt/prepared XML counts and official particle CSV, then
checks finite rows, integral Zone/Idp/Type/Mk, unique/consecutive UID, positive
mass/density, zero initial velocity, spatial non-overlap, source-box/profile
placement, 15 transverse fluid levels and Type0/Mk50 support in all six x
segments. Its exact DP lattice residual is reported at the original 1e-6
threshold as `numerical_precision`; it is explicitly excluded from the basic
placement gate and cannot grant Q-N or solver approval. This keeps the known
Root314 precision failure as evidence without blocking the stage-one physical
placement checks.

Root425 fixed the old fresh102 motion-template path/double-assets issue. The
fresh103 downstream requests carry root425_motion_rebind_required=true; Root
must replace the upstream attempt/path identities with the actual corrected
Root425/426 chain before enabling any downstream stage. Fresh102 bytes and all
historical failures remain untouched.

## Root execution entry

Run the metadata-only preflight from the F5 package:

/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python scripts/preflight_fresh103.py

After Root has actual candidate typed conversion JSON report/receipt, XMF
manifest/receipt and bed audit report, bind only their JSON metadata:

python scripts/bind_future_typed_xmf_bed.py --candidate A080 \
  --typed-report <actual conversion-report.json> \
  --typed-receipt <actual typed execution-receipt.json> \
  --xmf-manifest <actual xmf/manifest.json> \
  --xmf-receipt <actual xmf execution-receipt.json> \
  --bed-report <actual bed audit report.json> \
  --output-summary <root-owned metadata summary.json>

The same helper can bind the upstream JSON metadata before the downstream
products exist. Root426's actual GenCase receipt and prepared report can be
checked with:

python scripts/bind_future_typed_xmf_bed.py --candidate A080 \
  --gencase-receipt <actual GenCase execution-receipt.json> \
  --prepared-report <actual prepared-input-report.json> \
  --output-summary <root-owned GenCase metadata summary.json>

When later available, add `--initial-qa-report` and `--short-receipt` to bind
those stages in order. The helper checks producer-declared counts, 3-D/data2d,
and receipt identity from JSON only; it never opens XML/BI4/H5/CSV payloads.
With no product arguments it emits a null future plan. It never enables a
request, reads an H5/BI4/CSV/VTK payload, or grants visual/dynamic/full801
acceptance. Root must review the actual GenCase/prepared/initial QA/short native
receipts in order, then register CPU2 typed, XMF, and bed audit requests
sequentially. Full16/full801 and Q-N remain disabled until independent Root
review.

Source preparation facts: no job was started, no shared state or ledger was
written, no science array was read or hashed, and the package contributes zero
independent cases.
