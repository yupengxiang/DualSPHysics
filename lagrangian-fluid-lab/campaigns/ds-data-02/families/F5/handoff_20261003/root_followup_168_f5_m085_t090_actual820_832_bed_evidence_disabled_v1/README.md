# F5 fresh168: existing M085_T090 full801 bed evidence

This package is a source-only, disabled metadata binding for `F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T090`. The actual Root832 bed audit already exists for the same native 801-frame / typed H5 / Root832 XMF producer chain, so no duplicate bed science task is requested.

The existing producer receipt is completed/0 and its report covers all 801 saved frames, native particle axis 194427, initial fluid UID denominator 31658, Type-3 fluid in the exact source footprint, UID/nonfinite accounting, and 1DP/2DP diagnostics. The report remains `completed_worker_output_pending_root_review`; `repair_success` is unknown, production approval is none, Q-N is not granted, and visual/case acceptance remains pending.

Native Mk50 and source Mkbound40 are kept distinct. Canonical physical scope `cd77b07c6918a47a1bcbff5e1f066c36a34b0ca01d5f276e75d96a2d3dc89259`, source H5 legacy scope `8032a9ea54fe1fe0cf10b7944e4d38b07ef30a7895b83c1d088ef1621077b33a`, and source-plan scope `91723be071e6142a041a2d1229fcc015641ec3ebef52f0d3e03885c57c8499d8` are separate fields; no cross-resolution claim is made. The H5 SHA is producer-attested only.

The binding references the unchanged original fresh138 bed worker (`89be048da1df6bae49627308edb35a8a1936bc0888259cb5ab3d195307b550e2`), but all execution flags are disabled and all future bed/render hashes are null. `input_files` contain only regular JSON/XML/Python metadata; science payloads and directories are provenance-only.

Run the metadata-only check with:

```text
python3 scripts/validate_fresh168.py
```

This check verifies the existing completed receipts/reports and writes `metadata/fresh168-validator-report.json`; it does not start a job or read/hash H5, BI4, CSV, DAT, or VTK.
