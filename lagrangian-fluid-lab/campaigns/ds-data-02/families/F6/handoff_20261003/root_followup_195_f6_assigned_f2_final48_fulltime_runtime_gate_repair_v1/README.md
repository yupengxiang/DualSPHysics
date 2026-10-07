# F6 fresh195: F2 final48 full-time and runtime gate repair

This is a new F6-scoped successor to immutable fresh194. It is a metadata-only F2 final48 builder and validator. It consumes the exact checkpoint 282, Root1375 current index, Root1276 fixed membership, and Root1330 legacy correction catalog. It preserves `frozen8 ⊂ actual24 ⊂ registered48` in the supplied order and never selects cases by directory order, aliases, or accepted-count arithmetic.

The current inputs contain 44 accepted decisions and four pending physical IDs:

- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX049_RY014_FILL080_ROT075`
- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090`
- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090`
- `F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX061_RY014_FILL080_ROT090`

Fresh195 emits readiness only. It emits a final catalog only when all 48 rows have current accepted decisions and every selected primary chain passes the real metadata gates. A path existing or a decision claiming `completed` is insufficient.

For every accepted row the builder reads JSON metadata and performs these checks:

- native, typed, XMF, and render receipts use a genuine `ds02.execution-receipt.v1`, terminal `status=completed`, explicit `returncode=0`, and matching case binding; a `ds02.runner-request.*` object is never promoted to a receipt;
- the typed conversion report attests 401 frames, 3-D, particle count, PartVTK, increasing producer times, and a terminal typed receipt;
- the XMF manifest/XML and render report independently attest 401 temporal frames, N3 geometry/velocity shapes, matching producer/XML times, identity axis preservation, finite active fields, and per-frame missing counts;
- the XMF attempt has its own case-bound `ds02.execution-receipt.v1` with `status=completed`, `returncode=0`, a closed `input_files`/`input_sha256` key set, runtime `worktree_root`/`cwd`, and an output root that contains the selected `xdmf/manifest.json`; the render receipt is checked separately;
- the report's `input_manifest`, manifest `xdmf`, typed lifecycle frame summary, and XML time vector are cross-bound to the same case and producer time vector with a 1e-9 metadata comparison;
- the report's missing-particle counts and unknown causes remain metadata disclosures; they are never filled or converted into a precision or containment claim;
- initial-QA refs must be direct QA/audit evidence with an all-true check map plus prepared/GenCase/PartVTK/input scope, or a terminal case-bound audit receipt with an explicit input closure. Root QI summaries are not substituted for QA receipts. Native canonical, typed legacy, XMF plan, SourceDef, and source-plan namespaces remain separate, including absent fields;
- P03 keeps typed135's original `running`/null-returncode receipt byte-exact. Its only allowed substitute is the manifest's explicit recovery-aware provenance plus Root197's opaque artifact-integrity audit (`completed/0`, 401 frames, expected particles, arrays not decoded); that audit is recorded as recovery evidence rather than rewritten as an original typed success;
- `field_metadata_fulltime_certificate_verified` and `runtime_known_vs_original_unknown` are emitted per case. Q-N, Q-E, numerical precision, strict containment, all-UID survival, and mass equality remain false/unclaimed.

Root1330 has four explicit role corrections. The old `ds02.runner-request.v3` paths for RX046/ROT120, RX048/ROT065, RX048/ROT120, and RX052/ROT065 remain under `historical_source_render_request_role`. Fresh195 uses only Root1330's same-attempt terminal execution receipt and its paired manifest/XML/report, recording the correction provenance. It never silently replaces a request or invents a return code. The P03 original typed135 unknown/runtime boundary remains unknown unless its recovery-aware chain independently passes.

XMF/XML is parsed as metadata only; H5, BI4, IBI4, CSV, DAT, VTK, VTU, and PVTU paths are rejected before open or hash. PNGs are existence/stat references only. No solver, converter, renderer, QA, registry, ledger, cleanup, or case-credit operation is performed.

Build into a new or empty staging directory. Existing non-empty product directories are rejected, so a published readiness/final file cannot be overwritten:

```sh
python3 scripts/build_fresh195.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_282.json \
  --current-index /abs/path/full336-current313-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json \
  --output-dir /abs/path/new/fresh195-output
```

Validate the same frozen boundary. The validator runs synthetic negative checks for runner-request masquerading, a missing frame, a wrong producer time, an existing output directory, an XMF receipt bound to the wrong output root, and a bare `status=pass` QA report without direct input scope; all must be rejected. It then reruns the builder in a throw-away directory and checks the current 44/4 readiness boundary, Root1330 corrections, JSON SHA closure, and per-case runtime gate disclosures:

```sh
python3 scripts/validate_fresh195.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_282.json \
  --current-index /abs/path/full336-current313-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F2-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F2-FINAL48-ACTUAL42ACCEPTED-SIXPENDING-CORRECTED-PRIMARY-DELIVERY.json \
  --package-dir /abs/path/root_followup_195_f6_assigned_f2_final48_fulltime_runtime_gate_repair_v1
```

The package is assigned to F6 while its physical rows are F2. It creates no acceptance, production approval, Q-N/Q-E, numerical certification, or shared-state update. Fresh194 remains immutable history.
