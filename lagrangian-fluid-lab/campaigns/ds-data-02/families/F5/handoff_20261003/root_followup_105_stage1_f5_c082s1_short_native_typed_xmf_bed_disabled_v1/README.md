# F5 fresh105: Root455 short-native downstream binding

This is a source-only F5 handoff for the two already completed Root455
1 s/51-frame native runs:

* `A080`: `root-stage1-f5-c082s1-A080-short-native-qualification-104-root455`
* `A120`: `root-stage1-f5-c082s1-A120-short-native-qualification-104-root455`

The actual native receipts are completed/0, 3-D, 51-frame producer metadata
with total 194427 particles: fixed 158559, moving 4210, floating 0, and fluid
31658.  Fresh105 binds those receipt JSON files and keeps the corrected Root230
native policy identity.  The producer generated XML/BI4, motion DAT, and native
solver output remain Root-owned runtime inputs; this package does not open or
hash BI4/H5/CSV/VTK/DAT payloads.

Each candidate has three disabled, runtime-shaped requests:

1. NVME typed conversion (`cpu_task_kind=conversion`, cap2, 24 GiB staging,
   100 GiB free-space floor), with the real Root455 attempt as its dependency.
2. Legacy-aware XMF export (`cpu_task_kind=xmf_export`) using the F5 fresh079
   exporter.  Its canonical physical owner and future H5 legacy scope are kept
   as separate fields; the latter stays null until the producer report exists.
3. The fresh096 framewise Mk50 bed audit (`cpu_task_kind=audit`) over all 51
   states, with the exact x/z profile, y bounds, 1DP/2DP diagnostic bins,
   full-fluid UID denominator, nonfinite/lost UID reporting, and no acceptance
   threshold change.

All three requests have `disabled=true`, `launch=false`,
`execution_allowed=false`, null future output hashes, `full801_authorized=false`,
`q_n_granted=false`, and case increment zero.  The first-state zero-velocity
check and the existence/count of all 51 native `Part_*.bi4` files remain an
explicit Root precondition before typed conversion.  The historical exact-DP
lattice `1e-6` failure is preserved as an independent numerical diagnostic;
fresh105 does not relax or relabel it.

Validate the package with:

```text
python3 scripts/validate_fresh105.py
```

The JSON-only binder can bind the actual native receipt now:

```text
python3 scripts/bind_downstream_products.py \
  --candidate A080 \
  --native-attempt root-stage1-f5-c082s1-A080-short-native-qualification-104-root455 \
  --native-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/root-stage1-f5-c082s1-A080-short-native-qualification-104-root455/execution-receipt.json \
  --output-summary metadata/A080-downstream-binding.json
```

After Root has actual typed report/receipt, XMF manifest/receipt, and bed
report JSON, the same binder accepts all five metadata arguments and records a
review-only derived-product summary.  It never reads those payloads, enables a
request, grants visual acceptance, or authorizes full801.

No solver, converter, XMF exporter, bed worker, registry, ledger, or shared
state was modified or started during source preparation.  This handoff adds no
independent case.
