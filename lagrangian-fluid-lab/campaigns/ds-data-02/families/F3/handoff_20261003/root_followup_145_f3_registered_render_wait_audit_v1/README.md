# F3 fresh145 registered-render wait audit

This package records a metadata-only frontier check against frozen F3 checkpoint 180. The known unaccepted render registrations (1031, 1033, 1046, 1047, 1100, 1101, 1102, 1128, 1129, 1135, 1141, and the audit-aware 1194 successor) were probed by their recorded controller PID and `/proc/<pid>/stat` start ticks. Every controller was present with the same start ticks and no terminal receipt/report was published at capture time.

There is therefore no eligible completed render to inspect. This package contains no contact-sheet or keyframe review and grants no case credit. It intentionally does not read, copy, or hash H5/BI4/CSV/DAT/VTK payloads and does not launch or alter a job. Registration 1103 is explicitly excluded because it is already in the frozen accepted set. The original AY0270 conversion receipt remains a separate `running`/missing-returncode historical fact; it is not reclassified by this package.

Run `python3 scripts/validate_fresh145.py` from the package directory for the structural and metadata hash-closure checks.
