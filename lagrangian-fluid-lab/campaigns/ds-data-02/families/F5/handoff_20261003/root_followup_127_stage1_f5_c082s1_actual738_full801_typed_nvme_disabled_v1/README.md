# F5 fresh127: Root738 full801 typed NVME handoff

This package contains two disabled CPU conversion requests for the actual Root738 native endpoints `M085_T080` and `M115_T100`. Both native receipts were read as metadata and are `completed/0`; their producer counts are 194427 total, 158559 fixed, 4210 moving, 31658 fluid, 0 floating, 3D. The requests bind the actual native receipt/request, Root640 GenCase receipt and generated XML/BI4 attestations, Root661 initial placement/Mk50 QA metadata, and the fresh125 canonical physical IDs.

The package does not open or hash BI4/H5/CSV/DAT/VTK science payloads. The generated BI4 and native stdout hashes are copied as producer attestations. Each request is `kind=cpu`, `cpu_task_kind=conversion`, `cpu_threads=2`, `disabled=true`, `execution_allowed=false`, and uses the real NVME converter command shape with 24 GiB staging and the shared conversion cap of 2.

Canonical fresh125 physical scope and the legacy H5 owner scope are stored separately. The legacy scope is not a cross-resolution equivalence claim. The 5e-6-cell exact-DP precision negative remains historical evidence and is not relaxed.

The next Root-owned chain is per endpoint: typed `completed/0`, N3 XMF `completed/0`, all-801 bed audit, then Root visual approval. Only after both endpoint chains pass may the remaining ten complete non-T120 candidates be released. The four T120 candidates remain censored by the 16 s/801 window; fresh126 is a scope sidecar and cannot authorize them. No Q-N, production, visual credit, or independent case count is created here.

Run the metadata-only check with:

```text
python3 scripts/validate_fresh127.py
```

The manifest intentionally excludes itself and the generated validator report to avoid self-referential digests.
