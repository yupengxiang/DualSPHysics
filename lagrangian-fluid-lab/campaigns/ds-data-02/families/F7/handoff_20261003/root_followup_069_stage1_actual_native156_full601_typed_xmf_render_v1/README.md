# F7 fresh069: actual native156 closure and dependent typed/XMF/render requests

This package is source-only and disabled. It binds five existing F7 cases (`A035`, `A040`, `A050`, `A055`, `A060`) to their actual Root156 native receipts, Root117 per-case GenCase receipts, Root126 initial-QA reports, and immutable fresh065 canonical owners.

The native source contract is 70,179 particles in 3-D: fixed 27,495 (Type 0/Mk 10), moving 1,984 (Type 1/Mk 12), and fluid 40,700 (Type 3/Mk 2). The native fluid mass is 325.60001628 kg; the continuum envelope is 320.1984 kg. They are retained as separate quantities with no rescale. The motion reader is piecewise-linear absolute-angle increment; the sampled native input is not claimed C2.

Every typed request uses the unchanged Root110 NVMe wrapper and a 24 GiB staging guard, with a 100 GiB free-space floor and conversion concurrency cap 2. Root should enable the first two cases only after reviewing the disabled requests. Every XMF request writes to `{attempt_root}/xdmf`; every Root023 render request writes to `{attempt_root}/render`. The XMF vector shape contract is `outshape = shape[1:]`, so position/velocity dimensions remain `70179 3`.

The request `input_files` closures contain metadata, source code, XML, receipts, and immutable owner files. BI4, motion `.dat`, trajectory H5, CSV, and native data directories are recorded as Root-job-only payload provenance and are not read or hashed by this source build. Future producer hashes are null until Root completes each dependent job. `workers/assemble_fresh069_requests.py` can create enabled staging copies after Root supplies completed receipt/report/manifest metadata; it never opens scientific payloads and never edits these disabled templates.

No job was launched, no arrays were decoded, no shared registry or ledger was modified, and no Q-N, precision, dynamics, visual-acceptance, or production claim is made.
