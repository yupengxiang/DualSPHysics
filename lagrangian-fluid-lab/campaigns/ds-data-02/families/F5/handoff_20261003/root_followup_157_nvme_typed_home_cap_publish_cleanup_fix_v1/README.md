# F5 fresh157: exact publish bytes and BaseException cleanup

Fresh157 is a distinct source-only successor of immutable fresh155 (`2776ccd2`) and fresh156 (`1def68ac123af641445f84c99435e27c88ac4458`). It preserves fresh155 bytes and fixes two concrete wrapper defects found in source review.

The wrapper now defines `_report_payload`/`_report_bytes` locally and uses the same UTF-8 JSON serialization for the private preview and final report. It marks `publication_started` before the first atomic rename and catches `BaseException`, so the owned `SystemExit(143)` SIGTERM path removes Home partials and a destination that moved before the interrupt. The unchanged 4 GiB Home cap, 500 GiB floor, 2 GiB headroom, 24 GiB NVMe staging limit, 100 GiB NVMe reserve, 32 GiB typed estimate, ledger lock, converter, EOS, timeline, PartVTK checks, and hash semantics remain in force.

`tests/test_publish_cleanup.py` runs the real wrapper `run` with a fake converter and toy `.toy` bytes. It verifies successful exact report bytes and the verified-copy call, then injects a RuntimeError after verified-copy and a SystemExit after the first `os.replace`; all partial/final artifacts are absent after each failure. It does not import h5py, invoke the real converter, read or hash science payloads, launch a job, or touch shared state.

The disabled request template has no attempt, reservation, producer payload path, or future hash. Root must assign a new attempt and validate the final wrapper/source hashes before any registration. Fresh157 does not retire or modify any existing controller, receipt, ledger, or completed output.

Validation:

```bash
python3 -B tests/test_publish_cleanup.py
python3 -B scripts/validate_fresh157.py
```
