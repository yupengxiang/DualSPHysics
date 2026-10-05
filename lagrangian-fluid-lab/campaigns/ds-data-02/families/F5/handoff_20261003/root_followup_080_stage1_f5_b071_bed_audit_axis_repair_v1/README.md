# F5 B071 fresh080 bed-audit axis repair

This package is a source-only replacement for the fresh077 short-event bed
worker.  It corrects the native particle axis to the completed B071 producer
contract: 174896 total particles, consisting of 130392 fixed, 3794 moving,
and 40710 Type-3 fluid particles.  The actual bed marker is native Mk50;
source `mkbound=40` is retained as provenance.  The x profile, bed y interval,
0.02/0.04 m diagnostic bins, 51-frame scan, UID/nonfinite accounting, and
dynamic penetration interpretation are unchanged.

The canonical physical owner (`d791355f...`) and the typed H5 producer's
legacy-owner hash (`efa8c982...`) are separate proof layers.  The worker and
binder require the legacy scope metadata and reject a collapsed hash.  No
cross-resolution physical claim is made from the H5 attribute.

The binder performs the actual fresh079 typed-conversion and XMF receipt
checks before it writes a Root191 request.  It reads JSON/XML/source metadata
and uses the completed converter digest for the H5 input; it does not open BI4,
H5, or CSV arrays.  The generated request remains disabled and keeps
`full801_authorized=false`, `solver_allowed=false`, and
`independent_case_count_increment=0`.

After Root190 is actually completed, run from this package directory:

```text
python3 scripts/bind_bed_audit_fresh080.py \
  --typed-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json \
  --xmf-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-xmf-190/execution-receipt.json \
  --xmf-dir /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-xmf-190 \
  --output-dir /tmp/ds02-root191-f5-b071-bed-audit-axis-repair-source
```

Root must review and explicitly enable only the resulting CPU2 `audit`
request.  The 51-frame report is a short-event diagnostic; it cannot authorize
the rejected full 16 s/801-frame run or certify dynamic bed support by schema
checks alone.
