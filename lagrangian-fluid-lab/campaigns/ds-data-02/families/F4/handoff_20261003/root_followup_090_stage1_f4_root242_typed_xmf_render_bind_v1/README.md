# F4 fresh090: Root242 native to typed/XMF/render handoff

This F4 source package binds the six existing Root242 native attempts for
`F4_DROP_LATTICE_GAP0p19000_DP010`, `.20000`, `.21000`, `.23000`, `.24000`,
and `.25000` to the next three disabled stages:

1. the verified NVMe typed converter (two CPU conversion slots),
2. the temporal XMF exporter, and
3. the Root023 full-state renderer.

The native receipts are actual JSON evidence.  Each has the original Root230
attempt identity, the exact `-tmax:1.2 -tout:0.001` recipe, status `completed`,
and return code `0`.  They do not prove that the typed HDF5 has the expected
particle axis or all 1201 states.  `actual_typed_*`, XMF, render, frame, report,
H5, and image hashes therefore remain `null` until Root runs and independently
audits those stages.

The source builder and preflight read JSON, XML/metadata references, and small
source code inputs only.  They never open or hash BI4/H5/VTK/CSV scientific
arrays, launch a job, reserve a lease, alter the shared ledger, or add an
independent case.  Root-produced GenCase counts are retained as dynamic source
evidence: `83233 = 24161 fixed + 59072 fluid`, dimension 3.  The registered QA
job's raw array names are provenance only; this package does not reinterpret
them.

The typed and XMF requests use the unchanged native physical binding and exact
source recipe.  The Root023 render request has no diagnostic-frame argument:
it must scan all saved frames, preserve native geometry and all native fields,
and use the N3 Cartesian velocity contract (`vx`, `vy`, `vz`).  Camera metadata
is a provenance envelope; Root023 derives camera bounds from native valid points
and keeps the reader unclipped.  The 51 contact-page keys cover all 1201
frames.

Run the metadata-only checks with:

```text
python3 workers/preflight_fresh090_contract.py
python3 -m pytest -q tests/test_fresh090_contract.py
```

All 18 requests have `launch=false`, `launch_allowed=false`,
`source_only=true`, `launch_owner=root`, and
`independent_case_count_increment=0`.  Root must review the native receipt,
typed output report, XMF manifest, and full render report before any later
visual or production decision.
