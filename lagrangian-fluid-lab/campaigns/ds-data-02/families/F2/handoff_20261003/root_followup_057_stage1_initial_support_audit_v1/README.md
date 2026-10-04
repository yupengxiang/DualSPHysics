# F2 initial support and pre-rotation source audit (fresh057)

This scope records the source evidence needed to review the existing F2 matched
offset coarse case before changing any physics.  The bound case is
`F2_RV4EQ_MATCHED_OFFSET_V1_COARSE_DP010_SPATIAL_REFERENCE_SAVE010`, with the
existing fulltyped 401-frame trajectory and the existing full401 animation
artifact.

The canonical owner, current matched GenCase definition, generated XML, and
existing initial PartVTK QA metadata are inspected as text or JSON metadata only.
They establish a three-band fluid fill inside the cup envelope: physical cup
floor `z=0.65 m`, fluid box `z=0.70..1.02 m`, and three declared bound layers
`vdp=0,1,2` at `dp=0.01 m`.  The initial audit reports positive separation and
no fluid point inside the declared cup, receiver, or tray envelope.  The source
also declares uniform reference density `1000 kg/m^3` and zero initial fluid
velocity; the generated XML contains no hydrostatic pre-relaxation clause.

The existing visual handoff records wall-jet-like features at keys 25 (`~0.25 s`)
and 50 (`~0.50 s`) before or at the prescribed rotation start `0.5 s`.  That
observation remains descriptive and visual review is still pending.  The typed
metadata reports a coherent initial fluid cohort and a maximum of 118 missing
fluid identities out of 24,576 by the terminal frame.  This scope does not infer
explosion, invalid state, root cause, acceptance, Q-I, or Q-N from those facts.

A disabled Root-strict worker is included for an optional bounded frame-zero
check.  If Root enables it later, it reads only the first 51 particles of each
selected fixed-wall/fluid type from frame zero, reports position, velocity, speed,
kinetic-energy summaries, and sample-to-sample nearest distances.  It does not
claim a global nearest neighbour, does not write arrays, and does not launch any
job, GenCase, solver, conversion, or renderer.  This turn did not open the H5,
BI4, CSV, PNG, GIF, or raw particle arrays.
