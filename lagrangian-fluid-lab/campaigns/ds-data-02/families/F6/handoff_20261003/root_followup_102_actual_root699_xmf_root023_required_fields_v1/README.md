# F6 fresh102: Root699 XMF to Root023 renderer handoff

This source-only package contains 24 disabled Root023 full-241-frame render requests. Each case is bound to its own actual Root699 XMF registration metadata and its own future XMF receipt, `case.xmf`, and `manifest.json` paths. Root699 terminal completion is not asserted here; all future XMF and render hashes remain null.

Root142 admission fields are explicit in every disabled request: `worktree_root=/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics`, `cwd=/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab`, positive `estimated_storage_bytes`, `cpu_threads=24`, and `max_wall_seconds=14400`. The renderer environment limits each library/VTK/OMP thread setting to 2 and sets `MESA_GLTHREAD=false`. Root023 computes camera bounds from all native valid positions across the full saved time range, with no fixed camera or domain clipping.

The validator also parses the official XMF worker source and requires its literal binding fields, including `expected_frames=241`, before accepting the handoff. It includes a negative test proving that a missing `worktree_root` is rejected before reservation or worker execution. Root699 and Root698 are metadata-only inputs; this package never reads or hashes scientific H5/BI4/CSV/DAT payloads and never starts a job.

Fresh100/fresh101 and the failed Root684/Root694 attempts remain immutable historical evidence.
