# F7 handoff

The canonical registry now has 48 independent physical parents: 24 Pump and 24 moving-obstacle conditions. Production uses one candidate resolution (fine) per physical parent. A separate six-case reference matrix keeps one `physical_parent_id` across coarse/medium/fine for each mechanism. The prior 48 resolution views and their exact GenCase inputs are write-once under `archive/legacy_views/`.

The physical split is fixed before resolution views: 8 train, 8 validation and 8 test parents per mechanism. Nested subsets are 8, 24 and 48 cumulative cases; no legacy modulo-resolution split is reused.

The obstacle audit records the continuous fill volume, paddle overlap, narrowest clearance and expected fluid layers per `dp`. The old 6/10.752/12.460032 kg counts came from a seed inside the paddle and are retained only as archived evidence; corrected requests seed the connected fluid region and must be remeasured without mass normalization.

Historical Pump evidence is diagnostic only: old D05 reported 12 missing identities and 0.324 kg. Native solver requests must establish a closed mass ledger or an explicit open boundary flux/lifecycle ledger, plus source-zone, first-passage, residence, repeated-cycle and backflow labels.

Status: bounded GenCase evidence and six solver request plans only. No Q-I, Q-N or production claim is made. GPU/solver has not been started by this family.

Generated at 2026-09-30T20:59:41.534453+00:00.
