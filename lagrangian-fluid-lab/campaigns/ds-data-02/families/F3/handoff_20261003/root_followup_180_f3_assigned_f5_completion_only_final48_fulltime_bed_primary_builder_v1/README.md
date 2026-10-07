# Fresh180 F5 completion-only final48 builder

This F3-scoped package prepares a metadata-only F5 delivery catalog from the
frozen Root1293 membership, the Root1344 historical role catalog, and the
cp286/current-index pair.  It does not launch work and does not open or hash
H5, BI4, IBI4, CSV, DAT, VTK, or other scientific payloads. JSON receipts and
reports are read and hashed; XML/XMF and PNG references are stat-only.

The current cp286 source has **35 accepted and 13 pending** F5 cases. The
builder therefore emits `readiness.json`, never a pseudo-final48. It emits a
`final48.json` only when every fixed registered member has an accepted
decision, case-bound completed/0 native/typed/XMF/render/bed receipts,
full-time frame diagnostics, and complete primary visual references. Missing
publication receipts remain explicit; no alias or return code is invented.

Run it with all five explicit sources:

```bash
python3 build_fresh180.py \
  --checkpoint /abs/ROOT_LIVE_RESUMPTION_CHECKPOINT_286.json \
  --current-index /abs/full336-current314-actual-final48-delivery-progress-index.json \
  --membership /abs/F5-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/F5-FINAL48-CURRENT30ACCEPTED18PENDING-ACTUAL801-PRIMARY-BED-DELIVERY.json \
  --output-dir /abs/new-empty-output-dir
```

The output directory must be new or empty. Use the validator after the build:

```bash
python3 validate_fresh180.py --package . --output-dir /abs/output-dir
```

`tests/test_fresh180_contract.py` uses toy JSON and temporary directories to
exercise the overwrite guard, pseudo render-request rejection, missing refs,
and frame/time metadata failures. Those tests do not use campaign data.

The catalog preserves native canonical, typed legacy, XMF plan, bed
SourceDef, source-plan presence/absence, and historical publication-absence
roles independently. Case credit, Q-N, and Q-E remain zero.
