# F6 fresh090 Root558 QA / Root563 native binding

This package is metadata-only and source-only. It keeps fresh089 immutable and binds the corrected Root558 per-case initial native QA metadata to the disabled Root230 full-native recipe. Root558 reports are producer JSON metadata: 24/24 receipt `completed`/returncode `0`, per-case report `pass=true`, and index `pass=true` at package generation time.

Root555 is preserved as historical evidence. Its first attempt failed before PartVTK because the fresh089 prior typed-QA source SHA was stale; it is excluded from the current QA gate and is not rejudged.

Root563 is the authoritative already registered Root230 native attempt. `metadata/root563-native-binding.json` records its exact request and attempt roots; receipt hashes remain null until each Root563 receipt is terminal `completed`/`0`. The fresh090 no-suffix request copies are disabled and marked `superseded_by_actual_root563=true`, so they must not be launched.

FloatingInfo state0 remains a separate future audit. It is bound to each Root563 native request and receipt path, with `observed_omega_rad_s` and audit hashes null. GenCase particle V0 is not used as evidence for angular velocity.

The validators read JSON metadata and source request files only. They do not read or hash BI4, H5, CSV, DAT, Run.out, solver data, or arrays, and they do not launch jobs.

Validation:

```sh
PKG="$PWD/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_090_actual_initialQA558_native_binding_v1"
PYTHONDONTWRITEBYTECODE=1 python3 "$PKG/workers/validate_fresh090_root558_binding.py" \
  --package "$PKG" --output /tmp/f6-fresh090-root558-validation.json
PYTHONDONTWRITEBYTECODE=1 python3 "$PKG/workers/validate_fresh090_root563_binding.py" \
  --package "$PKG" --output /tmp/f6-fresh090-root563-validation.json
```

Root may rerun `workers/augment_root563_native_binding.py` only as a metadata refresh after new Root563 receipts exist; it never reads solver payloads.
