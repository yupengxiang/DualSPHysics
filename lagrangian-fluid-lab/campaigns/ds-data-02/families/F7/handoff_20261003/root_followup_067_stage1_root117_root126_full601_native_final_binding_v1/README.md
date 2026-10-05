# F7 fresh067 Root117/Root126 final full601 native binding

This source-only F7 package derives the five disabled full601 native solver requests from fresh066 and binds each case to the actual Root117 per-case GenCase receipt and actual Root126 initial native QA receipt/report.

Each Root117 per-case receipt is completed/0 and contains the runtime-required actual fields `total_particles=70179`, `fluid_particles=40700`, and `solver_dimension_from_gencase=3`. The Root117 top-level wrapper remains an immutable failed receipt (`returncode=0`, `GenCase actual particle count missing`) and is recorded as historical failure evidence; it is never rewritten as success. No GenCase rc0 or dimension is inferred from expected counts or XML.

Root126 has completed/0 receipt and a passing native-initial-qa report for all five cases. The full601 requests bind those actual QA hashes, genuine generated XML/BI4/Def hashes, and the Root116 prepared per-case solver cwd. Each cwd contains `motion_obstacle_quintic.dat`; the solver command preserves `-tmax:12` and `-tout:0.02` for 601 frames.

All full601 and historical QA requests remain `launch=false`, `launch_allowed=false`, and `execution_allowed=false`. Future solver execution-receipt, trajectory, and output hashes are null. No metadata-only qualified-input preparation request is needed because the runtime fields are present in every Root117 per-case receipt. No arrays, solver, GenCase, conversion, or shared registry/ledger state were touched.
