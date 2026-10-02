# F2 RV4-equivalent `dp=.005` precheck

This directory is a new, explicitly scoped finer reference candidate:
`F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002`. It is outside the original
48-case registry and has no qualification or production approval. The former
`F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC` remains a separate
negative scope because its finite geometry and motion/control bytes are not
RV4-equivalent.

The measured negative difference is explicit: the old CENTER COMM4 tray was
`[-.6,-.6,-.2] + [2.6,1.3,.1]` with a bottom-only face set, while RV4 uses
`[-1.2,-1,-.2] + [4,2,.15]` with bottom/left/right/front/back faces. The old
OFFSET receiver began at `y=-.08` while RV4 begins at `y=-.16`. The old
motion bytes hash to `547a941301b2a3d2fcce8633e4ff43b86fe08c4633c41e8fa9a0e85567f45c4b`
versus RV4 `ff966330e01e565987ebf182a7dfd7401d76577ae1c266894fc7db4aa34c5b70`,
with a measured maximum angle difference of 53.487915546 degrees. The old
physical hashes were CENTER `c1bc1a53cf66a697687b79ea236a9ff1c8e4416d0a4e138481ff58a82629dad3`
and OFFSET `061322d30e7579b7c4643d4d6f4f88d27cdb1abff6f636194725b8ed3a9ca569`.
The corresponding old/RV4 boundary canonical hashes were CENTER
`f1d62c22575eff1edb6407fc2f77faacc3c0b96b5e6af0319d04872e9afb3d9f` /
`c0c9c603620ee9f504d4cd66ed11bdfe0de3d2573eab8b35085b2aed4f1c168d`, and
OFFSET `a45b43e33383b3e079fabb2886051f2c19b172235039c0723a91771e9bcdeca0` /
`62b18e46a0d3da80fd6adf4c41c6e6bcf79471722a72229d6841913af4fbaa98`.
The new definitions therefore use a new scope and new case names instead of
relabeling the old negative outputs.

The two definitions start from the immutable RV4 medium staged XML for the
CENTER and OFFSET backgrounds. The finite cup is
`[0,-.15,.65] + [.425,.30,.45]`, the receiver is `[.45,-.30,0] +
[1.10,.60,.45]` for CENTER and `[.45,-.16,0] + [1.10,.60,.45]` for OFFSET,
and the tray is `[-1.20,-1,-.20] + [4,2,.15]`. The prescribed Y-axis motion,
axis points, control curve, execution parameters, 4 s window, and RV4 padded
simulation domain are copied from those staged inputs. The declared physical
condition hashes are the actual RV4 hashes:

* CENTER: `45c579bd9fa7a4878fcd25d0e0aa6dedf6da8c4cd77cd85e0d05b928ab8b6a43`
* OFFSET: `327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef`

The only numerical population changes are `dp=.005`, grid phase
`(-1.42,-1.2225,-.5625)`, and three disjoint fluid drawboxes. The continuous
fluid domain stays `[.0525,-.12,.70] + [.32,.24,.32]` m and is partitioned
into three Y bands of width `.08` m. Each band has explicit cell-centre point
`low + dp/2` and extent `size - dp`, giving 64×16×64 = 65,536 particles; the
total is 64×48×64 = 196,608 and the frozen continuous mass is 24.576 kg.

The shared v2 CPU GenCase receipts are external and immutable:

* CENTER: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_CENTER_V1/gencase-f2_rv4eq_dp005_center_v1-20261002-001/execution-receipt.json`
* OFFSET: `/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_OFFSET_V1/gencase-f2_rv4eq_dp005_offset_v1-20261002-001/execution-receipt.json`

Both completed with return code 0, solver dimension 3, 1,666,869 / 1,667,249
total particles, 196,608 fluid particles, and 190,138,935 / 189,957,496
output bytes. The independent PartVTK initial audit and additive occupancy
correction are under:

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_INITIAL_AUDIT/audit-f2-rv4eq-dp005-initial-20261002-001/reports/`

`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_INITIAL_CORRECTION/audit-f2-rv4eq-dp005-initial-correction-20261002-001/correction/rv4-equivalent-dp005-initial-correction-manifest.json`

The correction reports bind the actual CSV, generated XML/BI4 receipt, RV4
source XML/motion, and candidate definitions. Both backgrounds pass the
following initial checks: actual 3-D output; three 65,536-particle source
bands; unique `(Zone,Idp)`; RV4-to-source/generated physical projection
equality; identical motion bytes; all 196,608 fluid particles strictly inside
the initial cup; zero fluid points within `dp/2` of a cup face; zero receiver
or tray overlap; and 76,676 initial moving Type=1/Mk=17 nodes. The minimum
cup-face margins are 0.055, 0.0325, and 0.05249999 m by axis. Generated XML
`MassFluid=0.000125` gives authoritative native mass 24.576000 kg and
relative error about `1.22e-16` against the frozen continuous mass. These are
input and initial-state checks only; parent review is required before any
four-second GPU solver request.
