# RV4EQ DP005 deferred postprocess handoff

`f2_rv4eq_dp005_postprocess_handoff_v2.py` registers two additive CPU
conversion requests for the root-owned CENTER and OFFSET DP=.005 solver
trajectories.  It binds the co-located `.01 s` solver XML, copied BI4, motion
curve, GenCase receipt, physical RV4 source report, and explicit physical
binding.  The terminal solver receipt, complete `RunPARTs.csv`, and sampled
native Part files remain deferred until the root solver is completed and a
shared conversion slot is free.

The command uses the official full-frame `PartVTK_linux64`; `PartVTKOut` is
not a full-state decoder.  The requests use `ceil(Np * 401 * 64 * 1.40)` for
storage and retain `.01 s` as macro-spatial evidence.  They do not grant Q-I,
Q-N, or production eligibility.

`f2_rv4eq_source_binding_reconciliation.py` writes an external sidecar for
the consumed CENTER coarse label report.  The old label declaration points to
the pre-GEM production definition (`fluid_volume=0.018876 m^3`), while the
actual H5/conversion source is the RV4 GEM mother (`0.024576 m^3`, hash
`45c579...`).  The consumed H5, labels, report, and owner metadata remain
unchanged; the sidecar is required for any physical pairing review.
