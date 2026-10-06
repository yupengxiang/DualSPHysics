# F6 fresh112: delegated F4 visual acceptance

This source-only handoff records two additional old Root638 normal-render F4 cases after the fresh111 batch. The cases are:

- `F4_DROP_gap0p22000_xoff0p08000_yoff0p04000_uz0p40000`
- `F4_DROP_gap0p22000_xoff0p08000_yoff0p04000_uz0p60000`

I opened every `all_frames_000.png` through `all_frames_050.png` contact sheet and the nine key frames (0, 150, 300, 400, 600, 750, 900, 1050, 1200) for each case with `view_image`. I then computed SHA256 for those 120 PNG visualization artifacts. The render products report 1201 saved frames, complete contact sheets, preserved native times, preserved native identity axes, and zero reported nonfinite active states. The decisions are delegated decisions by `/root/f6_endpoint_initial_qa`; they do not claim that the root agent personally inspected the images.

The producer typed metadata lifecycle is retained without relabeling: transient_missing_frame_count is a cumulative frame-event count, maximum_missing_particles is the largest missing-particle count in one saved frame, and final_uid_state records final saved-frame UID presence/count metadata. These quantities are separate; a cumulative event count is never reported as a unique-particle total. Visual approval records the visible render only; it grants no Q-N, Q-E, precision, convergence, production, or global case credit.

Only JSON/XML/source/report metadata and the approved PNG visualization artifacts were read. No H5, BI4, CSV, VTK, or DAT scientific payload was read, copied, or hashed. No job, shared ledger, global checkpoint, or shared registry was modified.

Validate the package with:

```sh
python3 /home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_112_f4_delegated_visual_acceptance_v1/workers/validate_fresh112.py
```
