# F1 fresh078: Root164 native frame-0 Vx audit source handoff

This package contains eight **disabled CPU audit requests**. Each request binds one Root164 native solver receipt that was independently checked from JSON metadata as `status=completed`, `returncode=0`; DUAL cases retain 401 native frames and ECC cases retain 161.

The copied `native_initial_vx_frame0_audit.py` is byte-identical to Root164 (`sha256=189cdffa39343119b0e42b47732613501aca96553bc7c30918dafcbf696826e5`). It reads source XML's direct `initials/velocity` declaration and, only when Root enables the request, invokes official PartVTK on the solver-saved `solver_output/data/Part_0000.bi4`. GenCase BI4 velocity is explicitly not evidence. The source turn did not read or hash any BI4/H5/CSV bytes.

Each request is disabled (`launch_allowed=false`, `execution_allowed=false`), has `independent_case_count_increment=0`, `q_n=not_assessed`, and leaves the future saved-frame-0 BI4 hash and audit report SHA null. Root's strict CPU worker must create the isolated CSV/report and record the before/after native BI4 hash.

The input map is closed over non-array files only: local worker/binding/source plan/Def/owner/review/aggregate metadata, official PartVTK, actual GenCase receipt/report/generated XML/Def, actual Root164 native receipt, runtime/dispatch/goal, and Python. `input_files` and `input_sha256` are checked for exact set equality by `validate_source_contract.py`.

No Q-N, precision, visual, production, or accepted-case claim is made.
