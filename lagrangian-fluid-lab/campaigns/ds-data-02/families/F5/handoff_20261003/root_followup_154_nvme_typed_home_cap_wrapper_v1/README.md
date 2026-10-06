# F5 fresh154: capped NVMe typed successor

This is a source-only successor for the F5 typed conversion storage boundary. It adds `scripts/nvme_convert_home_capped_v1.py` without changing the integration direct converter, decoder, EOS, native time sequence, PartVTK checks, runtime, ledger, old requests, receipts, or completed outputs.

The wrapper forces decoder scratch, the temporary H5, and PartVTK validation CSV files into one private `/tmp/ds02-nvme-conversion` staging directory. It keeps the reviewed 24 GiB staging limit and 100 GiB free NVMe reserve. Every decoded frame checks the private staging peak and NVMe free floor after the decoder returns and reclaims that frame's decoder files; every selected PartVTK frame is checked while its CSV still exists. A final report preview is written and `stat`-measured on NVMe before the Home guard.

The Home guard uses the actual shared `resource-ledger.lock` while reading the JSON ledger read-only. It requires the requested `current_attempt_id` to match exactly one `reservations[].id`, sums all other reservations, applies the live ledger `home_min_free_bytes` with a minimum of 500 GiB, and keeps a 2 GiB publish headroom. The exact 4 GiB cap covers the staged H5 plus the final JSON report. A cap or floor failure occurs before any Home H5, report, or `.partial` file is opened. A passing guard uses the existing `verified_copy` attestation, fsyncs both private `.partial` files, and atomically renames them; an output appearing concurrently is rejected and a one-sided publish is cleaned up.

The cap is a hard refusal. It does not lower Root854's 32 GiB typed reservation or its 16 GiB wait margin, and it does not infer a reservation from observed compression. At the fresh153 snapshot Home had only about 24.69 GiB above the 500 GiB floor, so the existing 32 GiB typed reservation remained blocked even though observed H5 sizes were smaller. The successor stays disabled until Root supplies a fresh attempt and live reservation. Science `input_files`, payload hashes, and future outputs remain null here; producer workers must bind them at registration.

`metadata/retirement-plan.json` permits Root to retire only a disabled metadata wait controller that was never registered or running. It does not delete or edit old requests, receipts, reservations, or completed results. Any enabled successor receives a new attempt id and downstream XMF/bed/render bindings use that actual id.

Validation is bounded to source code, metadata JSON, and toy byte boundaries:

```bash
python3 -B tests/test_home_publish_math.py
python3 -B scripts/validate_fresh154.py
```

No real converter, solver, renderer, worker, shared controller, ledger mutation, or science-payload read/hash/copy was performed for fresh154. The package grants no Q-N, production approval, or case credit.
