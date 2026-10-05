# F5 B071 fresh081 metadata binding repair

Root191 stopped before opening scientific arrays because the prior worker
compared the actual GenCase receipt `output_root` with the generated XML's
`prepared/` directory.  Both paths are retained in fresh081 with distinct
roles:

- `gencase_receipt_output_root` is the actual Root163 attempt directory;
- `gencase_prepared_output_root` is its `prepared/` child containing the
  generated XML;
- `gencase_output_root` aliases the receipt attempt root for the receipt check.

The worker then rechecks the actual 163/175/185/187/189/190 JSON/XML metadata
before opening the native H5.  It preserves the native contract of 174896
particles (130392 fixed, 3794 moving, 40710 Type-3 fluid), 51 saved frames,
native Mk50/source `mkbound=40`, the exact bed profile and y interval, and the
0.02/0.04 m diagnostic penetration bins.  UID loss, nonfinite rows, and
initial fluid/profile separation remain explicit checks.  No penetration
threshold is relaxed and no dynamic success is inferred.

The canonical owner hash (`d791355f...`) and the typed H5 producer's legacy
owner hash (`efa8c982...`) remain separate proof layers.  The binder reads
actual JSON/XML/source metadata and registers the immutable H5 using the
completed conversion digest; it never opens BI4, H5, or CSV arrays.

After the already completed Root190 XMF receipt, generate the disabled Root201
request with:

```text
python3 scripts/bind_bed_audit_fresh081.py \
  --typed-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json \
  --xmf-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-xmf-190/execution-receipt.json \
  --xmf-dir /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-xmf-190 \
  --output-dir /tmp/ds02-root201-f5-b071-bed-audit-binding-repair-source
```

The resulting CPU2 `audit` request remains disabled until Root explicitly
reviews and enables it.  It keeps `full801_authorized=false`, solver disabled,
and independent case increment zero.  Root191's failed receipt remains a
historical negative attempt and is not modified.
