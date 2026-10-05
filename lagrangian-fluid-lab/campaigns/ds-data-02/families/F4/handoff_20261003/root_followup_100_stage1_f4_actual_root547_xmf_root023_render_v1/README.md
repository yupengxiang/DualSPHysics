# F4 fresh100 Root547 XMF to Root023 render handoff

This package is a source-only, disabled continuation for the 24 F4 cases. It
binds each request to the actual Root547 execution-receipt.json,
manifest.json, and case.xmf, while retaining the Root533 conversion JSON
and its observed Mk/Type/UID lifecycle. The metadata scan found the Root547
products at completed/0; it records those facts without reading or hashing
the referenced H5 trajectory.

Fresh099 remains immutable. Its older deferred paths included fresh098 XMF
and fresh099 render attempts, so every request here has a new fresh100
attempt/output root and points its renderer command at the Root547 manifest.
Future PVSM/GIF/report/receipt hashes are null.

All 24 requests are disabled, launch_allowed=false, CPU2, and Mesa
llvmpipe. Root must independently review and schedule Root023 under the
shared software-rendering cap. This package does not grant visual acceptance,
Q-N, precision, or production status.

Run the source-only checks with:

    python3 tests/validate_fresh100_source_contract.py

build_fresh100.py is a repeatable metadata poller. It may update only this
fresh100 directory; it never invokes build_fresh099.py, starts a job, or
opens/copies/hashes BI4/H5/VTK/CSV/DAT scientific payloads.
