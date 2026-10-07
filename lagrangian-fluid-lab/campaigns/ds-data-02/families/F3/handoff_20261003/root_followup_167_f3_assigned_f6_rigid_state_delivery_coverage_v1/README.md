# Fresh167 F6 rigid-state delivery coverage (assigned F3)

This package is a metadata-only, source-only audit prepared in the F3 worktree for the F6 final-48 roster selected from the Root1284 index. It does not add a case, grant visual credit, alter a request, or write shared state.

The decisive boundary is explicit: 47 final-48 rows have an official FloatingInfo audit whose command is bounded to `-first:0 -last:1` and whose JSON says `rows_examined: 2`. Those files prove state-zero omega fields and their units only. They do not prove pose, angular velocity, or linear velocity for frames 2 through 240. The special `DZXY_S1375_YAWP18_DP025` row is the same: its Root595 audit is state0-only while its native receipt advertises the full 241-frame solver run.

The baseline alias `F6_ANGULAR_RELEASE_DP025` is different. Its historical actual rigid-state report states a finite, monotone 241-frame history through 12 seconds, matching rigid rows to native saved times, and its full FloatingInfo receipt is completed. The Root1284 index still leaves that alias's current native scope unresolved, so this package preserves that role distinction instead of rewriting the index.

`metadata/full-time-floatinginfo-export-plan.json` is a disabled CPU2/root-owned plan for the remaining 47 cases. It uses the official FloatingInfo binary and requires `-first:0 -last:240`, all 241 rows, the full rigid field/unit set, and exact native receipt identity. It treats the existing 512 MiB per-case value as an estimate only. All future receipt/report/output hashes remain null until the primary registers and runs it.

The plan names the existing Root142 registration entrypoint and the state0 worker only as adaptation references. Root must register a strict CPU2 request through Root142; the existing state0 worker is explicitly insufficient until its bounded `0..1` read is replaced by a full `0..240` parse.

No H5, BI4, CSV, DAT, VTK, VTP, or other scientific payload bytes were opened, read, copied, or hashed here. CSV references in the coverage file are filename/stat evidence only. No solver, FloatingInfo export, renderer, or shared-state mutation was performed.
