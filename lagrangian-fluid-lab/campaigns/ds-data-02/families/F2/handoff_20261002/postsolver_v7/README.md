# F2 post-solver handoff v7

This directory contains additive, hash-bound handoff records. The producer
[`f2_handoff_20261002_postsolver_v7.py`](../../f2_handoff_20261002_postsolver_v7.py)
only reads completed solver evidence and writes requests; it does not launch a
solver, converter, or labels job.

The CENTER medium audit is an actual read-only audit of the completed RV4
full-state conversion. It records the 3-D H5 shape, typed cohorts, RunPARTs
loss accounting, moving-node position samples, finite PartVTK checks, and the
generated-XML MassFluid authority. The float32 H5 and decimal PartVTK values
remain separate display/adapter measurements. The audit and the v6 labels
request explicitly keep Q-I, Q-N, and production eligibility pending.

The temporal requests preserve the actual save and integration ratios. They do
not assert an exact half-step result. The DP005 requests use the official
`PartVTK_linux64` full-frame tool, but their full-window nonzero `NpOut` sums
place them in `dp005_pending_diagnosis/`; native unknowns are not classified as
physical spill and those requests must not be submitted before bounded loss
diagnosis.

The additive OFFSET medium v6 labels request completed through the shared v2
CPU runner from the immutable RV4 full-state H5. Its actual report is
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001/labels-f2h10v2-offset-v1-medium-rv4d1-baseline-save001-event-semantics-v6-pose-v2/f2-v6-observations.json`
(SHA-256 `f2f711b7e140a90173e80ed6f58bd66672b92bc81e1d2fa0144fd1ebd319a6a3`).
It contains 4001 frames through 4.000013621864287 s, authoritative native
mass 24.576 kg, three source layers of 1024 particles in the medium H5, and
the corrected RV4 physical hash
`327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef`.
Event counts are cup departure/return 1827/82, receiver entry/exit 843/0,
and tray entry/exit 907/196. The report remains observation evidence only:
Q-N is `not_assessed` and production is `not_evaluated`.
