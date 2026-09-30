# F7 handoff

The canonical registry now has 48 independent physical parents: 24 Pump and 24 moving-obstacle conditions. Production uses one candidate resolution (fine) per physical parent. A separate six-case reference matrix keeps one `physical_parent_id` across coarse/medium/fine for each mechanism. The prior 48 resolution views and their exact GenCase inputs are write-once under `archive/legacy_views/`.

The physical split is fixed before resolution views: 8 train, 8 validation and 8 test parents per mechanism. Nested subsets are 8, 24 and 48 cumulative cases; no legacy modulo-resolution split is reused.

The obstacle audit records the continuous fill volume, paddle overlap, narrowest clearance and expected fluid layers per `dp`. The old 6/10.752/12.460032 kg counts came from a seed inside the paddle and are retained only as archived evidence. The corrected reference GenCase attempt `GENCASE_05` completed through the shared runner with actual fluid masses coarse/medium/fine = 237.500/269.472/270.606336 kg, against the same continuous 320.1984 kg geometry mass; ratios are recorded as 0.7417/0.8416/0.8451 with no normalization. Domain z layers are 24/30/38. This is a discretization/geometry audit, not a qualification pass.

The read-only VTK audit is in `reference/geometry_particle_audit.json`. It parses the actual big-endian binary `Fluid.vtk` and `Bound.vtk` points, separates fixed and moving particles using the generated XML counts, and computes the continuous AABB intersection of the fill box with the paddle (0.0124416 m3); the tank wall surfaces are not charged as the full drawbox volume. For all three resolutions, fluid points form one 6-neighbor connected component with uniform z-layer counts and exactly equal the retained lattice cells minus the finite moving-boundary envelope (residual 0). The fine retained fluid lattice is 68 x 42 x 26 centers, with 9 x 35 moving-support cells excluded per z layer; its center gaps to the fill box are 0.014/0.014 m in x, 0.022/0.022 m in y and 0.022/0.010 m in z. This classifies the remaining mass difference as native finite-boundary/discrete initialization representation bias, rather than a continuous-volume arithmetic error or an unfilled connected fluid region. The native 270.606336 kg remains unresolved against the 320.1984 kg continuous ledger and is not a pass.

Historical Pump evidence is diagnostic only: old D05 reported 12 missing identities and 0.324 kg. Native solver requests must establish a closed mass ledger or an explicit open boundary flux/lifecycle ledger, plus source-zone, first-passage, residence, repeated-cycle and backflow labels.

The source and generated Pump XML motion trace is in `reference/pump_motion_audit.json`. It records 288/-288 degrees/s2 acceleration, 144/-144 degrees/s peak angular rates, 216/-216 degrees per 5 s forward/reverse cycle, and `TimeMax=12` s: two complete cycles plus the first 2 s of a third. The 601-row control CSV is only a sampling artifact; the cycle count comes from the actual XML schedule.

`split_plan.json` now records geometry/control holdout roles and a strict single-axis extrapolation plan. The current mixed-radix 24-parent table has no non-anchor parent that differs in exactly one axis, so those strict-axis roles are explicitly `planned_only_not_materialized`; current indices 12..23 are cross-factor geometry/control candidates, and only their existing `split=test` rows are evaluation holdouts. All three reference resolutions retain one parent and one split.

The six executable qualification request files under `requests/*-solver.json` bind the actual `GENCASE_05` BI4/XML prefixes, copied motion controls and input hashes. The shared runner request validator accepted all six; their max-wall estimates are 600/900/1500 s for obstacle coarse/medium/fine and 600 s for the three Pump references, with raw all-type storage estimates recorded per request. No GPU or solver has been started by this family.

Status: bounded GenCase evidence and six validated solver request plans only. No Q-I, Q-N or production claim is made.

Generated at 2026-09-30T10:09:29.693915+00:00.
