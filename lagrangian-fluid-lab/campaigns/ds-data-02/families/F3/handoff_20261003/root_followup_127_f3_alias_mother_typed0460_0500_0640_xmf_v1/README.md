# F3 fresh127: mother alias correction and three terminal typed handoffs

This is a source-only F3 package. It records that the census token `F3_STAGE1_DP006_P1000_AY0500` is an alias for the already accepted historical mother `F3_CELL3_LONG_DP006_AY0P50_ADAPTIVE_CFL05_COEF005` (`F3_TWOAXIS_AY0P50_PITCH_NOMINAL`, condition SHA `49e319c0a874733707a028e916362e74e2301d6681e34bc6b717581dbd7edaeb`). The missing P1000/AY0500 directory is therefore not a missing physical case and receives no new GenCase, native request, case credit, or visual status.

The package binds only three independently completed typed producer records that had no downstream XMF/render product at snapshot time: P0800/AY0460 (Root978), P0800/AY0500 (Root978), and P0800/AY0640 (Root991 decoder-CLI repair1). Each producer report says 836 frames, 179208 particles, dimension 3, and PartVTK all-pass. Reported H5 digests are retained as producer attestations; this source agent never opens or hashes H5/BI4/CSV/DAT/VTK payloads.

All XMF and Root023 render requests are disabled, `execution_allowed=false`, `case_credit=0`, and future XMF/render hashes are null. Source/canonical physical scope, actual converter scope, and historical legacy scope stay separate. Root must revalidate current input closures and owner scope before any enablement.

The validator checks every `bound_metadata_sha256` map and every non-science `input_sha256` map without reading scientific payloads.
