# F3 fresh067 native NVMe staging contract

This is a source-only design record for the next native-output handoff. It is
**blocked** against the current shared launcher. No native request is enabled,
no job was started, no active lease was touched, and no BI4, CSV, H5, HDF5,
NPY, or NPZ payload was read or copied.

The reviewed runtime is
`/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py`
(SHA256
`5098262e26dc5560487760181466b0a93a0e66239e5e54047dce5e761ae67a60`). Its
launcher always creates the attempt output below the Home `data_root`, applies
its storage checks to that tree/Home free space, and publishes one receipt from
the child process. Pointing a solver argument at `/tmp` would therefore put
bytes outside the runtime's reservation, live guard, and receipt accounting.
Wrapping the solver with a copier would also make archive failure look like a
native solver failure. The current CPU allowlist has no separate native archive
request or post-native hook. The requested eight native solver slots also need
review because the current reservation check caps active qualification/
production reservations at four; the observed conversion cap is two.

The minimum safe contract, before any enablement, is:

1. The shared runtime reserves Home and NVMe together, checks the 500 GiB Home
   floor and 100 GiB NVMe floor before launch and during the run, and charges
   every staged byte against a 24 GiB per-stage limit.
2. The official solver remains the direct child with the exact existing argv,
   cwd, XML/BI4, physical inputs, DP, `tmax`, `tout`, and frame recipe. Its
   return code is the authoritative native status, and the native receipt is
   atomically published only after that process exits.
3. A separate CPU archive request is created only from that completed native
   receipt and a frozen stat/digest manifest. It copies BI4/log/data artifacts
   from NVMe to the canonical Home attempt tree and records its own status and
   return code; it can never overwrite native status or release the GPU lease.
4. The stage manifest records source path, size, mode, `mtime_ns`, and SHA256.
   Copying is temporary-file plus fsync, followed by digest and source-stat
   rechecks and atomic publication. A failed copy leaves proof and the original
   runtime files unchanged.

`native-staging-contract.json` records these invariants, capacity observations,
future-hash null policy, and the exact runtime anchors. The read-only probe
`diagnose_native_stage_support.py --json` reports `blocked` until the shared
runtime implements them. Run the package check with:

```text
python3 -B tests/test_native_staging_contract.py
```

The package does not change the shared runtime, ledger, registry, global index,
or any F3 execution scope. It provides the smallest Root diagnostic and the
reviewable contract needed before a future staging implementation can be
considered.
