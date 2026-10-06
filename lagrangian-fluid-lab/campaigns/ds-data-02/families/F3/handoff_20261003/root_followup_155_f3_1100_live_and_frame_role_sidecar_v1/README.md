# Fresh155 F3 live-handle and frame-role sidecar

Observed at `2026-10-06T23:39:36.950013+00:00` UTC. This package preserves the only currently active registered F3 render handle, **1100**. Its receipt was still `running`, with a live controller/dispatcher/worker chain and no published report at capture. No visual review was performed and the handle was not restarted, stopped, or edited.

The five pre-existing records 987, 1031, 1033, 1046, and 1047 have a concrete metadata role split: their top-level `ds02.runner-request.v2` envelope says `expected_frames: 801`, but its command passes the per-case wrapper. The loaded `ds02.stage1.f3.fresh114.nvme-render-successor.v1` wrapper says `expected_frames: 836`, `expected_particles: 179208`, and `expected_contact_sheets: 35`; each upstream review records the all-836 geometry/velocity/exact-time and native-UID checks. The sidecar records the discrepancy and does not rewrite either source.

Only JSON and process metadata were read. Scientific payloads (H5, BI4, CSV, DAT, VTK, XMF, PNG) were not opened, read, copied, or hashed.
