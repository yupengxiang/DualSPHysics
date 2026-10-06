# fresh140 F3 AY0270 process audit and render wait

Audit time: `2026-10-06T20:47:42.486414+00:00` UTC. This package is source-only and scoped to F3.

The preserved AY0270 typed receipt `root-stage1-f3-ay0270-full836-typed-nvme-154` records `pid=2367325`, status `running`, null returncode, and start time `2026-10-05T01:26:52.442570+00:00`. Historical checkpoint snapshots identify launcher PID `2367173`, reservation time `2026-10-05T01:26:49.851638+00:00`, and host `user-SYS-421GE-TNRT`. Neither historical PID is present in the current `/proc` probe; neither historical start tick was preserved. CP173 contains no matching active reservation. The conversion report says its own conversion output is complete, but that report is not an OS process-exit receipt. The package therefore preserves the state as unfinalized and gives Root a qualified-reconciliation prerequisite; it does not relaunch, settle, or rewrite anything.

The two current F3 render controllers are Root1128 (P1200/AY0500, PID 239294, start ticks 210260427) and Root1129 (P1200/AY0540, PID 239500, start ticks 210261151). Both controllers were sleeping with no child at the probe and had no local terminal render receipt or full-animation report. No visual case was selected. The source package contains metadata only and does not open or hash H5, BI4, CSV, DAT, VTK, PNG, or other scientific payloads.
