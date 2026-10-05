# F6 fresh088 mechanical-pose / multi-axis omega source package

This package proposes 24 new F6 physical tuples to extend the checkpoint082
accepted 24 toward a 48-case family target. It combines four non-axis-aligned
angular component patterns (`DXYZ`, `DYXZ`, `DZXY`, `DYZX`), six sparse omega
scales (`0.375, 0.625, 0.875, 1.125, 1.375, 1.625`), and official GenCase
`initials/rotateaxis` yaw poses (`-18, -12, -6, +6, +12, +18` degrees). The
body center remains the accepted `[2.4, 1.2, 1.08]` m center so the reviewed
wall/fluid clearance contract remains available to Root's later native QA.

Every Def XML keeps the accepted DP0.025 3D finite tank, zero fluid velocity,
free translation/rotation DOFs, physical mass 128 kg, native support mass 256
kg, masspart 0.015625 kg, and `TimeMax=12`, `TimeOut=0.05` (241 frames).
`rotateaxis` is the official GenCase initials operation about the declared body
center; it does not add forcing, MDBC, motion files, or solver options.

The package contains 24 canonical owners, independent source-plan hashes,
genuine GenCase requests, a disabled 24-case native PartVTK QA binding, a
disabled per-case FloatingInfo state0 omega audit, and disabled full241 native
qualification requests through Root146. Type/Mk/UID/finite/3D/native-count
fields are prospective contracts; actual GenCase receipts and native evidence
must confirm them. Particle V0 remains insufficient to infer angular state.

No GenCase, solver, PartVTK, FloatingInfo, converter, renderer, BI4/H5/CSV/DAT/
IBI4 reader, scientific array hash, shared registry mutation, visual approval,
Q-N result, precision result, or production credit was produced here. Future
scientific paths and hashes are intentionally null. QA019 and semantic020 are
carried as exactly two immutable historical records and are not rejudged.
