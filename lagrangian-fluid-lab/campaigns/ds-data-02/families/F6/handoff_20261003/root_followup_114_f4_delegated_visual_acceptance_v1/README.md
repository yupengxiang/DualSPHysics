# F6 fresh114: delegated F4 visual review

This source-only package records two independent F4 aligned-lattice products selected with the explicit gap priority:

- `F4_DROP_LATTICE_GAP0p20000_DP010`
- `F4_DROP_LATTICE_GAP0p21000_DP010`

The Root638 replacement inventory was checked first. It contains 24 cases at gaps 0.18, 0.22, and 0.24, and contains no gap-0.20 case. These selected cases therefore come from the separate official aligned-lattice pipeline; the package records that lineage difference and does not relabel them as Root638 replacement cases. Fresh109 through fresh113 and checkpoint-099 accepted decisions were excluded from selection.

I personally inspected every `all_frames_000.png` through `all_frames_050.png` contact sheet and the nine key frames (0, 150, 300, 400, 600, 750, 900, 1050, 1200) for each case with `view_image`. The package records SHA256 and byte size for all 120 PNG artifacts after viewing. Both render reports attest 1201 source/rendered frames, preserved native times, preserved native identity axes, zero nonfinite active states, and complete contact-sheet output.

The visual observations describe the rendered tank, drop, impact, splash, settling, and late central features. They do not infer UID survival, particle count, angular or numerical accuracy from an image. The producer metadata for these aligned cases has fixed=24161, fluid=59072, moving=0, floating=0, total=83233, dimension=3; the generic renderer text mentioning type-1/type-2 fields is not evidence of nonzero populations. Producer UID/lifecycle metadata is retained separately, and this review records no independently observed late UID exclusion.

Actual converter scope, canonical consumer binding, source-declared physical scope, and source-plan scope are recorded separately. For these schema-repaired products, the consumer canonical binding equals the actual producer physical scope; the older source-declared scope remains separately recorded. The producer H5/BI4 digests are metadata attestations only. I did not read, copy, or hash H5, BI4, CSV, VTK, or DAT scientific payloads.

The PNG titles retain `VISUAL REVIEW PENDING ROOT` and `PRECISION NOT ACCEPTED`; this stale provenance text is recorded as a limitation. These are delegated decisions by `/root/f6_endpoint_initial_qa`, not claims of root-personal image inspection. No Q-N, Q-E, precision, convergence, production approval, or global case credit is granted.

Validate the package with:

```sh
python3 /home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_114_f4_delegated_visual_acceptance_v1/workers/validate_fresh114.py
```
