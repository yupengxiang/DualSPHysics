# F4 resting-pool migration definition

This is the conditional migration record for the new F4 resting-pool family. It is activated only if the standard F3 production or fine baseline24 rows fail their fixed gates. It does not infer that result early, relax any gate, or add another F3 repair. The complete definition and matrix are in [f4-resting-pool-migration-spec-2026-09-19.json](/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/material/evidence/f4-resting-pool-migration-spec-2026-09-19.json).

The family is `F4_drop_resting_pool_x_v2`, revision `F4_resting_pool_13plus2_v2`. The continuous source is the falling drop box

```text
x = 0.25 + 0.22*q .. x + 0.26,   y = 0.12 .. 0.28,   z = 0.40 .. 0.54
```

with initial velocity `(0, 0, -0.5) m/s`. The continuous destination is the resting pool box `x=0..1.2`, `y=0..0.4`, `z=0..0.18 m`. Native Mk labels remain numerical provenance only; independent material seeds receive source labels from continuous box membership and never from `particle_id`.

Events use the pool free surface `z=0.18 m`: contact is the first downward crossing, upward propagation is the first later upward crossing, and return is the first later downward crossing. Residence is time inside the destination box after contact. A completed return needs the post-return gravity-time window of 0.3497487083913345 s. The registered horizon is 4.34 s with one whole-scope extension to 8.68 s when an event is right-censored; full event completion is required.

The scope is the already prepared 15-cell matrix: q=0, .5, 1 at dp=.01/.0075/.005; held-out q=.25 and .75 at dp=.0075/.005; and center q=.5 dp=.0075 internal-time and native-output controls. The JSON lists every case, prepared file, and existing job id. The matrix is qualification-only and does not inherit prior F4 T1 or production status.

The resting-pool canary has passed structural and mass checks but covers only 0.3 s and reports `event_window_complete=false`, so it cannot qualify the family. Wait for the root-owned T1 matrix and its full-window gate receipt before queuing any material overlay. Existing F4 scheduler entries must be reconciled by root; this evidence file starts no CFD or GPU job and mutates no central ledger.
