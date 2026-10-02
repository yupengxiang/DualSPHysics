# F3 weak-dual time-study handoff (2026-10-02)

This namespace contains additive source copies and runnable requests for two
independent time controls on the already completed F3 weak-dual reference:

* `half_dt`: fixed `DtIni = DtMin = DtFixed = 1.106134843353494e-5 s`,
  exactly half the measured native `2.212269686706988e-5 s`, while retaining
  `TimeOut = 0.0025 s`;
* `half_save`: retains the adaptive time-step parameters and changes only
  `TimeOut` to `0.00125 s`.

The baseline Run.out records this input cadence as `TimePart=0.0025 s`;
the handoff keeps the XML parameter name (`TimeOut`) separate from that
runtime evidence label.

The continuous tank, initial fluid volume, gravity, acceleration CSV,
boundary parameters, solver controls and physical binding remain the same.
The original definition, control CSV, Run.csv, RunPARTs.csv, Run.out and
consumed HDF5 artifacts are read-only inputs.  The source manifest records
their hashes and the owner physical binding hash.

The CPU requests are bounded GenCase/initial PartVTK/native accounting work.
The GPU requests are prepared for the root launcher through
`ds_data02_runtime_v2.py`; this handoff does not start a solver and does not
grant Q-N.  Downstream requests cover streaming direct conversion, full typed
label sidecars, and a fixed physical `0--10 s` macro/time-bracket diagnostic.
