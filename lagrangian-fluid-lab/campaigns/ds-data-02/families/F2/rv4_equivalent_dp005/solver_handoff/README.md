# RV4-equivalent DP005 solver handoff

This is an additive root-review handoff for the new
`F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002` scope. It carries two
solver requests, one CENTER and one OFFSET, each using a fresh solver XML
derived from the completed DP005 GenCase artefact with `TimeMax=4 s` and
`TimeOut=0.01 s` (401 expected native save frames). The original GenCase XML
with its `.001 s` finer-reference cadence is retained and hash-bound; only the
solver XML's numeric save cadence changes. The requests are root-owned inputs and do not
grant Q-I, Q-N, or production eligibility.

The solver prefix is a fresh, co-located copy under
`/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/F2_RV4EQ_DP005_NATIVE_INPUTS_20261002/`:
each case directory contains its solver XML, BI4, copied motion curve, and a
provenance sidecar. The BI4 and motion copies are byte-identical to the
completed GenCase outputs; the XML records the additive `.001 -> .01` solver
cadence change. Request storage is derived from the actual total particle count:
`ceil(Np * 401 * 64 * 1.40)` bytes.

The native domain preflight reads the actual initial PartVTK CSV, retains
fixed Type=0 and moving Type=1 cloud bounds, sweeps the moving Type=1 cloud
through the prescribed 0 to -105 degree curve, and adds the generated
support radius `2 * hdp * dp = 0.013 m`. Both backgrounds pass with positive
low/high margins. This proves initial native cloud and prescribed boundary
sweep containment in the numerical domain; it does not classify any later
fluid loss as physical spill.

The physical projection compares RV4 finite boxes, constants, execution
controls, simulationdomain, rotation axis, four-second motion window, and
motion bytes. The only recorded numerical changes are `dp=0.005`, grid phase,
and explicit cell-centred fluid blocks. Old COMM4 DP005 remains a separate
negative scope.
