# F4 fresh097: Root514 frame-0 PartVTK velocity audit to typed handoff

This package is source-only and disabled. It follows the 24 Root514 full1201
native attempts. `build_fresh097.py` reads only the matching execution-receipt
JSON files and refreshes the status snapshot, frame-0 bindings, and typed
conversion requests. It never opens, copies, or hashes native BI4, PartVTK CSV,
H5, DAT, or other solver payloads.

The frame-0 worker is a Root-owned CPU audit. After the matching native receipt
is completed/0, Root must materialize the scientific input closure and run the
official PartVTK command on `Part_0000.bi4`. The worker observes raw `Mk`,
`Type`, `Vel.x`, `Vel.y`, and `Vel.z`, checks the owner-declared velocity by
marker, and records the observed frame-0 row count. It does not trust the
GenCase velocity declaration as native evidence and does not pad a frame whose
native row count differs from the GenCase count. The report cannot grant Q-N,
visual acceptance, or production approval.

The typed requests stay disabled until the matching frame-0 report passes. At
that point Root must run the converter's actual physical-condition-scope
preflight. The source owner hash and source-plan hash are retained as
provenance; neither is presented as the converter scope hash. Typed H5/report
and receipt hashes remain null here. Conversion concurrency is capped at two,
NVMe staging at 24 GiB, and Root must preserve the 100 GiB NVMe and 500 GiB
Home floors and foreign-GPU protection.

Root471's strict continuum/lattice diagnostic and Root500/501 history remain
negative historical evidence. This package does not change the solver recipe,
the 0.01 m spacing, the 1.2 s window, or the 0.001 s save interval.

Run the source validator after building:

```text
python3 tests/validate_fresh097_source_contract.py
```

The validator checks request/binding closure and future-null boundaries only;
it does not invoke the shared runtime or any scientific decoder.
