# F5 B071 fresh079 post-conversion pipeline

This source-only package repairs the fresh078 metadata gates against the real enabled Root189 request and the producer's direct conversion report schema. It does not modify fresh077, the native worker, the runtime, or the strict dispatcher. It never opens BI4, H5, or CSV scientific arrays and never launches a job.

The real Root189 request is:

`/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_b071_actual_native187_typed_conversion_189/typed-conversion-request.json`

Its actual contract is `depends_on_attempt` plus `actual_bindings.short_solver_receipt_sha256`, `nvme_policy`, and `conversion_contract.mass_report_without_rescale`. It does not use the old `native_solver_*`, `nvme_protocol`, or `native_3d_required` fields. The correct native axis is 174896 total particles: 130392 fixed, 3794 moving, and 40710 fluid, in native 3D. The completed execution receipt's top-level `output_root` is the authoritative typed output directory; the request itself has no `output_root` field.

The direct converter report must use `ds-data-02.bi4-direct-conversion.v1`. For B071, metadata validation requires 51 frames, 174896 particles, 3D with producer field `solver_dimension.xml_data2d == "false"`, strictly increasing `time_evidence` through 1 s, `typed_identity` containing native Mk50 and types 0/1/3, and `storage_protocol.verified_published_output_sha256 == output_sha256`. PartVTK metadata is checked at the producer's declared frames 0/25/50; it is not dynamic bed acceptance. The report's `hash_scopes.physical_condition` is explicitly `legacy-owner-scope.v0` with no cross-resolution physical claim; the canonical XMF binding remains `d791355f...` and is never replaced by the report's legacy digest.

Before Root189 runs, validate the actual enabled request shape without touching products:

```text
python3 scripts/verify_post_conversion_metadata.py \
  --typed-request /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_b071_actual_native187_typed_conversion_189/typed-conversion-request.json
```

A deliberately wrong total such as 214385 must fail this check. After Root189 completes, pass the real receipt and report:

```text
python3 scripts/verify_post_conversion_metadata.py \
  --typed-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json
```

Then assemble the disabled normal-XMF request:

```text
python3 scripts/assemble_post_conversion_pipeline.py \
  --stage xmf \
  --typed-receipt .../root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report .../root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json \
  --output-dir /tmp/ds02-root189-f5-b071-post-conversion-xmf-source
```

The generated XMF request uses allowlisted `cpu_task_kind=audit`, CPU2, and a fresh079 legacy-aware copy of the fresh077 exporter. The source binder independently verifies the actual GenCase163 XML and receipt hashes plus the native187 request/receipt chain before binding canonical `d791355f...`. The exporter validates the immutable H5's legacy physical attribute against the producer report, while preserving the canonical owner hash as a separate binding. It preserves native fields, native time values, all 51 frames, and source H5 read-only. H5 is registered in `input_files` with the converter report's `output_sha256`; the binder does not rehash H5. Strict dispatch performs the final runtime input check.

After the real XMF request is `completed/0`, bind the disabled bed and render requests with `--stage downstream`, `--xmf-receipt`, and `--xmf-dir`. The bed request uses allowlisted `audit`, CPU2, source `mkbound=40 -> native Mk50`, exact profile x domain `[-0.2,4.8]`, bed y domain `[-0.15,0.15]`, and diagnostic 1DP/2DP bins `0.02/0.04 m` for every actual frame. The render request uses allowlisted `audit` and the renderer from the successful Root023 proxy-lifetime diagnostic (`5e78f7b9...`), CPU2, all 51 actual frames, native fields and times, contact sheets, and Root visual review. The historical fresh077 renderer (`545f5a50...`) remains recorded only as provenance. Thresholds and render integrity do not authorize physics or full801.

All generated downstream requests remain disabled; `full16_authorized`, `full801_authorized`, `q_n_granted`, and production approval remain false/none. No full801 request is created. Historical A061 penetration failure and native187 evidence remain separate and are not overwritten.
