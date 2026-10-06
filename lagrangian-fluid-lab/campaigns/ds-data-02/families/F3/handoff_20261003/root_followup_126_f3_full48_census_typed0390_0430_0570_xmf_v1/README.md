# F3 fresh126: full48 census and three terminal typed handoffs

This source-only F3 package records a 48-condition inventory and prepares disabled downstream XMF/Root023 requests for exactly three newly terminal typed producers: F3_STAGE1_DP006_P0800_AY0390, F3_STAGE1_DP006_P0800_AY0430, F3_STAGE1_DP006_P0800_AY0570. The fresh125 AY0290/AY0320 handoffs and actual977 AY0360 are excluded.

The selected producers are bound to their immutable `execution-receipt.json` and `conversion-report.json` metadata. AY0570 uses the Root991 decoder-CLI-repair1 terminal producer; the earlier Root981 wrong-decoder `failed/1` receipt remains under `metadata/negative-evidence/` and is never treated as success. Typed reports contribute only producer-reported metadata (836 frames, 179208 particles, 3D, PartVTK all passed); this package does not open or hash H5/BI4/CSV/DAT/VTK payloads.

`metadata/full48-source-census.json` enumerates the P1000 first24 plus P0800/P1200 pitch-AY conditions. It is an inventory of source/evidence status, not visual acceptance, precision qualification, production credit, or a claim that all 48 have complete outputs. Missing source directories and unselected terminal products remain explicitly recorded.

All XMF/render requests remain disabled, `source_only=true`, `execution_allowed=false`, and `case_credit=0`. Future XMF, render, visual, and H5 outputs remain null. Root must revalidate current producer receipts, owner scopes, and resource leases before enabling any request.

Run the metadata-only validator:

`python3 scripts/validate_fresh126.py`
