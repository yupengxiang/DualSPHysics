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
