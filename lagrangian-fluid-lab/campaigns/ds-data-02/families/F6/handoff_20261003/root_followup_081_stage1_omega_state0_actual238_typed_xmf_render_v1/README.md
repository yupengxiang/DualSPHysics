# F6 fresh081: Root238 state0 metadata -> disabled typed/XMF/render chain

This is a source-only F6 handoff for the eight stage24 omega cases at scales 0.30, 0.40, 0.60, 0.90, 1.10, 1.30, 1.60 and 1.90. Root229 full241 native receipts, Root226 initial native QA, Root223 producer-attested GenCase XML/BI4 hashes, canonical owners, and source-plan hashes are retained as separate evidence.

Root238 is now actual metadata: its one aggregate execution receipt is `completed` with return code 0, the aggregate omega summary passes all eight cases, and each per-case `state0-omega-audit.json` passes. The aggregate receipt and the eight reports are bound by `metadata/actual-root238-state0-provenance.json`. Root238 explicitly has no per-case execution receipts; this package does not invent any.

The eight `typed/requests/*full241-typed-nvme-request.json` files are disabled conversion requests. They use the Root142 CPU audit/conversion entry, retain the mother recipe (`-tmax:12`, `-tout:0.05`), full 241 frames, 3D native contract `417505` with vector shape `417505 3`, and the unchanged NVME/cap policy. They keep physical rigid mass 128 kg, native support mass 256 kg, and solver interaction `masspart` 0.015625 kg distinct with no rescaling.

The XMF and Root023 render files are disabled downstream templates. Their output hashes and all conversion/XMF/render future hashes remain null. No visual, Q-N, precision, or production acceptance is claimed. Source workers and contracts are reused immutably from fresh080; no solver, converter, PartVTK, ParaView, BI4, H5, CSV, or shared registry operation is performed by this package.

`workers/assemble_fresh081_chain.py` performs only metadata and source hash closure checks. It verifies the Root238 aggregate/per-case evidence, disabled flags, Root142 entry, N3 vector contract, mass semantics, future-null policy, and absence of invented per-case receipts.
