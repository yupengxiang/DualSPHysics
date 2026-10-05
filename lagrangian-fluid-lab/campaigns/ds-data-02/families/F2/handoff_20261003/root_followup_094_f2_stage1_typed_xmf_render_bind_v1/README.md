# F2 fresh094: Stage1 typed/XMF/Root023 handoff

This source-only package audits the only two F2 Stage1 native-109 endpoint
receipts present in the data root. It records P01 and P03 as the two next
handoff slots, while making their lifecycle difference explicit:

* P01 has a genuine typed135 completed/returncode 0 receipt, a completed
  conversion report, existing normal XMF153, and existing Root023-160 output.
  fresh094 provides metadata-only reuse gates; it does not launch duplicates.
* P03 has native109 completed/0 and the same actual population
  418104/21114/372840/24150 in 3D, but its original typed135 receipt remains
  running/returncode null with tool status 143. Root197 independently
  verified the published H5/report opaquely with audit returncode 0;
  Root257 XMF is completed/0 and Root258 render lifecycle is preserved. This
  package never relabels the original converter as OS returncode 0.

P07 is listed in metadata/exclusions.json as pre-registered without any actual
native109 evidence. The old matched-offset mother is support-only and is
excluded from the physical-case count.

All five requests are disabled metadata gates (launch_allowed=false,
execution_allowed=false). The Root142 NVME contract is recorded in
metadata/root142-nvme-contract.json with a 24 GiB stage cap and 100 GiB
free-space floor, but no new conversion candidate exists in this cohort.
Scientific artifacts are only deferred references with null future hashes.
The validator reads JSON/XML/source metadata and refuses H5/BI4/CSV/VTK
suffixes.

No solver, converter, XMF worker, renderer, array read, shared registry write,
or ledger mutation was performed by this handoff.
