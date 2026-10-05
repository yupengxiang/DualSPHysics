# F7 fresh075: actual GenCase metadata adapter

This package is a source-only handoff for the next24 F7 target-angle cases.

It repairs the fresh074 path contract for Root343's flat GenCase output:
`<attempt_root>/prepared/<case>.xml`, `<case>.bi4`, `<case>_Def.xml`, and
`prepared-input-report.json`. The adapter reads bounded JSON/XML metadata only;
it checks BI4 and motion-file presence but never reads or hashes their payloads.

The native initial-QA worker is disabled. When Root enables it, official
PartVTK writes isolated per-case CSV files and the worker checks UID, type/Mk,
finite positive fields, zero initial fluid velocity, unique coordinates,
no gross overlap, true 3D, and the separately reported native and continuum
fluid masses. It does not grant visual, Q-N, precision, or production status.

The adapter also emits one bounded runtime-evidence JSON sidecar per case.
Root's qualification runtime requires top-level actual particle counts, while
the Python GenCase wrapper receipt can omit those parsed fields. The sidecar
derives them from the completed prepared report and generated XML, preserves
the raw receipt provenance, and lets the disabled native request satisfy the
runtime contract without opening BI4.

All request templates are disabled, owned by Root, and keep future receipt,
BI4, CSV, native solver, and output hashes null until the actual producer job
has completed. No source script launches GenCase, PartVTK, or DualSPHysics.
