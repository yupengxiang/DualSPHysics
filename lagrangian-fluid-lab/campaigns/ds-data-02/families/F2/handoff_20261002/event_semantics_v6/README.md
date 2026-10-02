# F2 v6 event semantics

v6 is an additive observation operator.  It preserves the v5 and consumed
source bytes while testing the moving cup local-z top opening at the
interpolated crossing pose.  The world particle segment and saved rigid-body
angle are interpolated at the signed top-margin crossing, so an endpoint may
be outside the cup footprint while the crossing itself is inside it.

Native invalid identities remain unknown.  Closed finite-wall crossings,
legal tray candidates, and open-top/domain exclusions remain separate source
evidence.  v6 writes a `cup_top_crossing_aperture` dataset and reports first
and all-observed event bracket widths.  It grants no Q-N or production status.

The old-six source trajectories are legacy `.01 s` saves (401 frames over
approximately 4 s), so their first observed event brackets are about `.005 s`.
The RV4 baseline and temporal requests are separate `.001 s` or finer studies;
their results must be bound to their own trajectory, recipe, and operator
hashes.
