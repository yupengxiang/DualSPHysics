# F4 fresh081: eight internal drop-gap source bindings

This family package contains eight genuinely distinct `dp=0.01` finite drop/pool gap conditions at `0.185, 0.195, 0.205, 0.215, 0.225, 0.235, 0.245, 0.255 m`. Every source Definition is an exact byte-local mutation of the immutable DP010 mother: only the mk=1 drop point `z` literal changes. The pool, drop x/y, drop velocity `(0,0,-0.5)`, tank/walls, DBC/Verlet/Wendland recipe, `TimeMax=1.2`, `TimeOut=0.001`, and full 1201-save contract remain fixed.

The existing accepted mother, gap 0.18, and gap 0.26 are counted once as three members of first8. The first five new internal points complete first8; the final three are first24 extensions. This package adds no accepted case and reports `independent_case_count_increment=0`.

All GenCase, native qualification, initial-native QA, NVMe typed conversion, XMF, and 51-page native-bounds render requests are source-only disabled requests. No request is enabled by this commit. Root's strict order is: `requests/gencase-aggregate.request.json`; each per-case `*-initial-native-qa.request.json`; each `*-full1201-native-qualification.request.json` through Root146 `launch.py`; each `*-full1201-typed-nvme.request.json`; each `*-xmf.request.json`; then each `*-render.request.json`.

No BI4/H5/CSV arrays were read or copied while producing this package. Future receipt/output hashes are null. Native fluid marker semantics remain explicit: source `mkfluid=0/1` maps to generated native mk values 1/2; a native marker is never a particle count.

Historical F4 negative spatial/integration evidence remains immutable and is referenced in `source-plan.json`; no tolerance, Q-N, precision, visual, or production claim is changed.
