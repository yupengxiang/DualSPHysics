# F1 fresh092: actual initial-QA to full-native binder

This source-only package binds the 24 actual fresh091 GenCase completed/0 products to disabled Root230 full-native qualification requests. ECC cases retain the 1.6 s / .01 / 161-frame recipe; DUAL cases retain 4.0 s / .01 / 401 frames and the complete physical event window.

The actual receipt, prepared report, generated XML/Def, source owner, and source plan are metadata/XML inputs. The producer-attested BI4 digest is recorded as provenance and the BI4 remains a future Root input; this package never reads or hashes BI4, H5, CSV, DAT, or VTK payloads. Initial-QA receipt/report paths and hashes are null until Root supplies the actual fresh091 policy-repaired completed/0 outputs.

Every native request is disabled (`execution_allowed=false`, `launch_allowed=false`, `disabled=true`) and routed to the Root230 launch/policy closure. The native frame-0 PartVTK velocity gate is a separate disabled request and must pass before any typed conversion. The fixed worker uses the prepared report's `actual_generated_constants.data2d` and generated XML z bounds, avoiding the historical XML-path-only check.

Use `scripts/materialize_fullnative_after_initialqa.py` with an explicit Root per-case JSON receipt/report manifest to make a new disabled staging copy after actual QA. No source script resolves a GPU or launches a job.
