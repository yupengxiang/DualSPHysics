# F5 fresh155: CLI-entry repair for the capped NVMe typed successor

Fresh155 is an independent source-only successor of committed fresh154 (`138b1aa176b33eb6b2b554e71a68baa78eec6b1e`). The fresh154 helper, storage guard, and historical package bytes remain preserved. Fresh155 fixes one real entry-point defect: the old `__main__` parsed wrapper flags into `opts`, parsed direct-converter flags into `args`, then called `run(opts, ...)`; `opts` did not contain `output`, `report`, `data_root`, or the other direct inputs. The repaired entry point keeps the two parsers separate, merges their namespaces, and passes that merged namespace to `run`.

The NVMe/Home protocol is unchanged: decoder scratch, temporary H5, and PartVTK CSV remain private to the 24 GiB NVMe staging area with a 100 GiB free reserve; the direct converter, EOS, full timeline, three-frame PartVTK validation, and payload hash semantics remain unchanged. The exact 4 GiB H5 plus final JSON Home cap, live 500 GiB floor, ledger reservation accounting, actual `resource-ledger.lock`, reservation identity check, and atomic `.partial` publication remain unchanged. The old 32 GiB typed estimate is not lowered.

The toy test injects a fake direct parser and fake runner. It sends both wrapper arguments (`staging_root`, `current_attempt_id`, staging limit) and direct arguments (`data_root`, generated XML, output, report, decoder, receipts, owner) through the actual CLI parsing and asserts that the fake `run` receives them in one merged namespace. Its toy H5/report paths are placed directly under an existing temporary attempt root, so the test does not assume a missing `typed` subdirectory can be created. It does not import the real h5py converter, invoke conversion, touch Home, or read a science payload.

`metadata/fresh155-successor-request-template.json` stays disabled and carries no science input paths or future hashes. `metadata/retirement-plan.json` permits Root to retire only an unregistered, non-running metadata wait controller; old requests, receipts, reservations, and completed results remain untouched. A future enabled request must receive a new attempt id and bind downstream outputs to that actual attempt.

Validation:

```bash
python3 -B tests/test_home_publish_math.py
python3 -B scripts/validate_fresh155.py
```

No real converter, solver, renderer, worker, controller, ledger mutation, or science-payload read/hash/copy was performed for fresh155.
