# F2 fresh102 GenCase runtime evidence and initial-QA handoff

Fresh102 binds the sixteen actual Root353 GenCase execution receipts to their
producer prepared-input-report JSON and generated XML. Raw receipts are
referenced and hashed as immutable JSON; they are not rewritten. Partition
counts come from the actual prepared report, not from a fabricated receipt
field.

Each case has one disabled CPU initial-QA request and one disabled full-window
native request. The QA request runs the existing fresh100 prepared-report
contract audit before the PartVTK frame-zero audit. The native request uses
the exact DP=0.01, 4 s, 0.01 s/401-frame recipe and depends on a future actual
QA pass. All future QA/native receipt and scientific-output hashes remain
null.

Source preparation opened only JSON/XML/Python/text metadata and did not read
or hash motion .dat, BI4, H5, CSV, VTK, or XMF payloads. The prepared motion
asset digest is carried from the Root353 producer report without re-reading
the asset; the Root-owned QA/solver job will perform its runtime input checks
when enabled. No qualification, production, visual, precision, or Q-N claim
is made.

The request closures bind the fresh100 workers, actual Root353 JSON
receipt/report/XML, source owner metadata, Root142/Root230 policy, strict
dispatch, runtime, resource approval, and per-case evidence sidecar.
