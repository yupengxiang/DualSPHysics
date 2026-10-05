# F4 fresh101 source100 input closure audit

This package independently audits all 24 fresh100 request JSON files. It
recomputes SHA-256 only for non-scientific inputs such as JSON, XML, Python,
text, the approved renderer binary, and /usr/bin/env. BI4, H5, CSV, DAT,
VTK-family, and other scientific payload paths are skipped before opening.

The audit found two stale Root533 execution-receipt digests. Both current
receipts are the same exact typed attempt and are completed with returncode
0; the current digest also matches the corresponding Root547 manifest
typed_receipt_sha256. The repair checklist records the before hash, current
hash, status, attempt, Root547 manifest, and Root561 review evidence. Root
must apply any corrected request independently.

Source099/source100 are immutable. This package starts no jobs and writes no
shared registry or ledger state.

Run:

    python3 tests/validate_fresh101_source_contract.py
