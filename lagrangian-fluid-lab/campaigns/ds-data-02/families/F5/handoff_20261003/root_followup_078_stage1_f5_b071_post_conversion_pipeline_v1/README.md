# F5 B071 fresh078 post-conversion pipeline

This package is a source-only handoff for the real Root189 typed conversion. It reuses the fresh077 native XMF, Mk50 bed audit, and full saved-frame renderer without copying or changing their scientific code. `scripts/assemble_post_conversion_pipeline.py` binds actual metadata after Root189 exists, then creates disabled downstream request files with strict input registrations. It never opens BI4, H5, or CSV scientific arrays and never launches a job.

The assembler accepts the converter report's verified `output_sha256` as the immutable trajectory H5 digest. It does not rehash the H5. Every generated request still registers the H5 path in `input_files`; Root's strict dispatcher must perform the final runtime digest check. JSON/XML/source inputs are hashed normally. The assembler rejects BI4/CSV paths, live `resource-ledger.json`, and mismatched `input_files`/`input_sha256` sets.

The typed receipt must be actual `completed/0` for `root-stage1-f5-b071-short-native-typed-nvme-189`, with nested `case_id`, `cpu_task_kind=conversion`, `cpu_threads=2`, 51 frames, 214385 total particles, 40710 fluid particles, native 3D, and native bed marker Mk50. The conversion report must be `ds-data-02.bi4-direct-conversion.v1`, completed, 51 frames, 214385 particles, 3D, strictly increasing actual times through 1 s, PartVTK metadata pass, and `storage_protocol.verified_published_output_sha256 == output_sha256`. These checks are metadata checks; they do not certify dynamic bed penetration.

Run the first assembly only after the actual Root189 receipt and report exist:

```text
python3 scripts/verify_post_conversion_metadata.py \
  --typed-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json

python3 scripts/assemble_post_conversion_pipeline.py \
  --stage xmf \
  --typed-receipt /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report /home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071/root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json \
  --output-dir /tmp/ds02-root189-f5-b071-post-conversion-xmf-source
```

Review the generated XMF request before enabling it. Its `cpu_task_kind` is allowlisted `audit`, with two CPU threads. The XMF worker must preserve all native H5 fields, actual time values, 51 temporal frames, physical condition hash, and source H5 read-only. XMF output is a derived view and does not add an independent case or establish physics acceptance.

After Root has actually completed the XMF request with `completed/0`, bind the bed and render requests. The downstream assembler validates the actual XMF receipt, `case.xmf`, and manifest metadata before writing requests:

```text
python3 scripts/verify_post_conversion_metadata.py \
  --typed-receipt .../root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report .../root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json \
  --xmf-receipt .../root-stage1-f5-b071-short-native-xmf-190/execution-receipt.json \
  --xmf-dir .../root-stage1-f5-b071-short-native-xmf-190

python3 scripts/assemble_post_conversion_pipeline.py \
  --stage downstream \
  --typed-receipt .../root-stage1-f5-b071-short-native-typed-nvme-189/execution-receipt.json \
  --conversion-report .../root-stage1-f5-b071-short-native-typed-nvme-189/conversion-report.json \
  --xmf-receipt .../root-stage1-f5-b071-short-native-xmf-190/execution-receipt.json \
  --xmf-dir .../root-stage1-f5-b071-short-native-xmf-190 \
  --output-dir /tmp/ds02-root190-f5-b071-downstream-source
```

The bed request uses allowlisted `audit`, CPU2, exact profile x domain `[-0.2, 4.8]`, bed y domain `[-0.15, 0.15]`, source `mkbound=40 -> native Mk50`, and diagnostic 1DP/2DP bins `0.02/0.04 m`. It requires every actual saved frame and reports UID loss, nonfinite positions, and unexplained changes. Thresholds are diagnostic bins, never an approval gate.

The render request uses allowlisted `preview`, CPU2, and the existing renderer. It requires all 51 actual frames, native fields, exact native times, contact sheets, a full animation, and Root visual review. Render integrity and XMF integrity do not certify dynamic physics. All generated requests remain disabled; `full16_authorized`, `full801_authorized`, `q_n_granted`, and production approval remain false/none until Root separately reviews the real short-event bed report and visuals. No full801 request is created by this package.
