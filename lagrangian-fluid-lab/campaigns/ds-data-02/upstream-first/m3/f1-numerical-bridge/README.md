# F1 dp=.015 numerical bridge preparation

Status: **prepared metadata only; no GenCase or solver has been launched here**.

The immutable official mother is `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml` (`sha256=1f7cca807e16a3b1a1cc4da649a68db5166439d3f4b30fa4ea25635baf6045b7`). It remains a
reference-only source. The three small XML copies are:

- `/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m3/f1-numerical-bridge/input/UF_F1_MDBC_DP015_BASE_Def.xml` — `UF_F1_MDBC_DP015_BASE`, the same official dam-break condition with
  `casedef/geometry/definition@dp` changed from `0.01` m to `0.015` m. This is a
  numerical bridge, not a new physical condition.
- `/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m3/f1-numerical-bridge/input/UF_F1_MDBC_DP015_H050_Def.xml` — `UF_F1_MDBC_DP015_H050`, copied from the bridge and changing only
  `casedef/geometry/commands/mainlist/fillbox/size@z` to `0.50` m.
- `/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m3/f1-numerical-bridge/input/UF_F1_MDBC_DP015_H060_Def.xml` — `UF_F1_MDBC_DP015_H060`, copied from the bridge and changing only
  the same fillbox `size@z` to `0.60` m.

The machine proof is in `/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m3/f1-numerical-bridge/semantic-diff.json`. It compares the official mother to the
bridge, then the bridge to each child. Each comparison has exactly one allowed
attribute change and no other semantic XML change. The constants and execution
control digests match, including `TimeMax=6` and `TimeOut=0.01`; the full control
snapshots and source/copy hashes are in `/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/upstream-first/m3/f1-numerical-bridge/input-manifest.json`.

## Bounded planning scales

The rough counts and raw-storage scales are planning values only. They use the
parent-provided official F1 facts (1,015,809 total particles, 652,212 fluid,
601 frames, about 18.19 GiB raw native output at `dp=.01`) and ideal volume
scaling `(0.01/0.015)^3 = 8/27`. The bridge therefore has a rough 0.2963 volume
scale and 0.4444 surface-area scale; actual GenCase counts, frame bytes,
compression, runtime, and terminal receipts remain authoritative. The `.50` and
`.60` candidates are then rough volume scales of `0.50/0.55` and `0.60/0.55`
relative to the bridge. No exact boundary-area estimate is asserted.

The three request files under `requests/` are GenCase-only, use the extensionless
definition prefix required by official GenCase, target `upstream_nas`, and require
the parent NAS preflight. `BASE` is the only first-order submission candidate.
`H050` and `H060` stay gated until BASE is compared and explicitly accepted as a
numerical bridge. No acceptance, equivalence, or production claim is made here.
