# F2 fresh096 actual GenCase bound QA/native handoff

This source-only package binds the five Root270 GenCase attempts for the fresh095 RX047/RX050/RX055/RX060/RX063 conditions. Each receipt is completed with return code 0 and its own generated XML, BI4 producer hash, prepared-input report, and measured particle counts. The measured counts are kept per case; no mother count or mass is substituted.

The five disabled `actual-initial-qa` requests use the reviewed dynamic PartVTK worker and point to the actual Root270 receipt. Root may enable a request through the shared CPU runner to produce a bounded frame-zero report. The five disabled Root230 native requests carry the actual GenCase receipt/report/XML/BI4 producer bindings, but keep QA and native output hashes null and remain forbidden until the corresponding actual QA passes. The exact native command is the existing full 4.0 s / 0.01 s / 401-frame command with no added mDBC/no-slip option.

Root269's strict-dispatch preflight rejection is preserved as historical evidence and is never treated as a completed GenCase. Root270 runtime, strict-dispatch, Root142 home-floor, resource-window, Root230 home-floor, source-policy, and GPU-policy digests are recorded. No GenCase, PartVTK, solver, array reader, shared registry, or ledger was run or modified by this package.

`build_fresh096.py` is a metadata-only regeneration helper. The copied `f2_stage1_initial_qa_worker_v2.py` is disabled source for Root's later CPU audit; it is not executed here.
