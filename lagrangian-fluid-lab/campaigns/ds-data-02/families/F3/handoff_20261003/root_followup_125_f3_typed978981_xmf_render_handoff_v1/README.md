# F3 fresh125: Root978/981 typed-to-XMF/Root023 handoff

This F3-scoped source package prepares the disabled downstream handoff for the 19
physical cases in Root978 (12) and Root981 (7). Each case has its own physical
condition, owner scope, native terminal receipt, typed attempt lineage, XMF
binding/request, Root023 wrapper request, and render request. The package adds no
case credit and starts no task.

At the read-only snapshot (2026-10-06T15:52:20.552106+00:00), the AY0290 and AY0320 typed attempts had terminal
`completed`/`returncode=0` receipts plus completed conversion reports. The remaining
entries were absent/not submitted at this snapshot. These are
observations only; Root must re-read each terminal JSON receipt/report before
activating the corresponding XMF or render request. Typed H5 output digests are
used only when reported by a terminal producer conversion report; this package
never opens or hashes H5/BI4/CSV/DAT/VTK payloads.

The XMF request uses the exact fresh104 `export_xmf.py` source (SHA
`da50e26d5322b1b6f1539bca3109dfc115164427b37e1b2f86f56b153f56b0b0`) and keeps
source physical scope separate from actual converter scope. The Root023 handoff
uses the exact fresh116 manifest-path repair wrapper (SHA
`5d577e4b28e62906472bfba30ad445685f804be4ba5d8bab44b4bab3d32e1621`) and the
mature renderer (SHA
`5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66`). The
wrapper preserves the original absolute manifest argument, uses full 836-frame
rendering, CPU24/env2, NVMe cap24 GiB, Home floor500 GiB, Home publish cap3 GiB,
and renderer cap2. All XMF/render products and visual decisions remain future
null/WAIT in this source package.

Run the static validator from this directory:

`python3 scripts/validate_fresh125.py`

The validator reads only JSON/Python/XML metadata and does not call the XMF,
ParaView, NVMe, runtime, or shared ledger workers.
