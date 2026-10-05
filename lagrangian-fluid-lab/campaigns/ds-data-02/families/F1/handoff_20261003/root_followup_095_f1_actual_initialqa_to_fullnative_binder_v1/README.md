# F1 fresh095: actual Root473 initial QA to disabled Root230 full-native

This source-only handoff binds the 24 actual Root473/474 initial-QA products to new disabled Root230 full-native qualification requests. The actual QA receipt and report for every case are `completed`/returncode `0`; each report passes its GenCase/official PartVTK metadata checks, reports 3D, and agrees with the producer GenCase total/fluid/non-fluid counts.

ECC keeps the existing full physical recipe (1.6 s, `tout=0.01`, 161 frames). DUAL keeps the existing full physical recipe (4.0 s, `tout=0.01`, 401 frames). The official solver command, prepared GenCase prefix, generated XML/Def producer digests, Root230 dispatch policy, home/NVMe guard, and resource window are carried forward unchanged. No forcing, MDBC, motion, CPU solver option, mass rescaling, or time-window mutation is introduced.

All `full-native-requests/*.json` and the separate `native-frame0-requests/*.json` are disabled: `execution_allowed=false`, `launch_allowed=false`, `launch=false`. A live GPU UUID lease is resolved only by Root230 at enable time. Future native receipts, native counts, saved-frame-0 audit outputs, typed outputs, and Q-N/production evidence remain null or explicitly pending. The frame-0 PartVTK gate is separate and required before typed conversion.

The source agent reads JSON/XML/source metadata only. It does not open, copy, or hash BI4, H5, CSV, DAT, VTK, or other scientific payloads. BI4 and official CSV digests appearing in producer reports are retained as attestations with `source_agent_read_* = false`; raw GenCase velocity declarations are not solver-saved frame-0 velocity evidence.

Run `scripts/verify_actual_initialqa_binding.py --package <this-directory>` before Root review. The verifier checks the 24 actual QA receipts/reports and non-payload static hashes, skips producer-attested scientific payload bytes, and rejects any enabled request or non-null future output hash. It performs no solver launch and does not resolve a GPU.

Historical fresh091/fresh093/fresh094 failures remain preserved in their original handoffs and are not rebound as passes. This package does not grant Q-N, visual acceptance, or production approval.
