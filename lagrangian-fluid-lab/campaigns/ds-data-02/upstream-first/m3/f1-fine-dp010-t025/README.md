# F1 fine dp=.01 / TimeOut=.025 derivative drafts

Status: **prepared metadata only; no GenCase or solver launch**.

The immutable official source is `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml` (`sha256=1f7cca807e16a3b1a1cc4da649a68db5166439d3f4b30fa4ea25635baf6045b7`). The two definitions are exact copies except for one physical fill-height attribute and one separately declared output-schedule attribute:

- `UF_F1_MDBC_DP010_H050`: `fillbox/size@z` `0.55 -> 0.50` m.
- `UF_F1_MDBC_DP010_H060`: `fillbox/size@z` `0.55 -> 0.60` m.
- Both retain `dp=0.01` m, `TimeMax=6` s, all physics/geometry controls, and set `TimeOut=0.025` s. The `TimeOut` change is numerical/output sampling metadata, not physical-axis credit.

Machine proof is in [`semantic-diff.json`](./semantic-diff.json): each candidate has exactly one physical change and exactly one separately labelled output-schedule change. Per-case single-physical-difference manifests are under [`manifests/`](./manifests/), and request drafts are under [`requests/`](./requests/).

The mother declared-use gate remains pending the full 601-frame native identity/finite audit, root-owned M3 scope review, and resource preflight. The failed `dp=.015` bridge does not transfer acceptance. Solver drafts bind no GenCase receipt yet and remain forbidden to submit. Existing `m3/f1-numerical-bridge/` definitions and requests are untouched.
