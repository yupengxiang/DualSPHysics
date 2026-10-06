# fresh110 F3-scoped F6 NVMe renderer successor

This package prepares an independent, disabled successor for the 24 F6 full241 cases. Root722 metadata proves all 24 existing XMF products are `actual_completed0_N3_pass` with 241 saved frames and particle axis 417505. Root860 is retained as historical evidence only: its controller is still a wait process, its own directory has no render request, execution receipt, render output, or controller result at audit time. The successor removes Root860's wait on the unrelated F4 Root856 batch and binds directly to each case's own Root722 manifest, XMF, typed receipt, and native receipt metadata.

`workers/nvme_render_successor.py` preserves the Root732 command contract: `pvpython --force-offscreen-rendering render_native023.py --manifest {manifest} --output-dir {stage_render}`. It requires a future Root reservation with `reservation_id == current_attempt_id`; the disabled source request is never executable. Root must derive an enabled binding with `source_only=false`, `future_input_hashes_null=false`, and a checked `input_files`/`input_sha256` closure for non-payload metadata. It runs the complete saved-time renderer in a private NVMe `render/` directory, retaining every frame PNG, all 11 contact sheets, seven declared keyframes, `full_saved_animation.gif`, `case.pvsm`, and the full JSON report. It does not permit diagnostic-frame subsets.

The wrapper enforces a 24 GiB stage cap, 100 GiB NVMe free floor, and 3 GiB explicit Home publication cap. It holds the real `resource-ledger.lock`, rereads the live `resource-ledger.json` limits and reservations, excludes the own reservation from other storage/thread/cap totals, and uses the live approved 500 GiB Home floor. The static `home_reserved_bytes` field is never used as a substitute. It rewrites report and private PVSM paths to the final Home path, serializes and rechecks the final report/receipt sizes before publication, hashes only derived render files, and atomically renames an exclusive sibling directory. It refuses existing products and leaves Home untouched when a cap, floor, wall, renderer, process-group, or byte-verification check fails. Successful and rejected attempts remove private staged render bytes; rejection leaves only a small NVMe JSON record.

All 24 source requests are disabled and future scientific input hashes are null. The package does not open or hash BI4/H5/CSV/DAT/VTK. Root023 is the future CPU reader of the registered XDMF/H5 source. The source package does not modify Root860, shared requests, controller state, registry, ledger, or receipts. The wrapper’s runtime ledger read is lock-scoped and read-only; Root remains responsible for creating the reservation and enabling a request.

Validation commands:

```text
python3 scripts/validate_fresh110.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Numerical precision, visual acceptance, Q-N, and independent case credit remain outside this source handoff.
