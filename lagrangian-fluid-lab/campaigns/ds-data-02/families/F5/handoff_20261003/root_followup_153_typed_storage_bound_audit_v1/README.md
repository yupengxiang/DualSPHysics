# F5 fresh153: typed-storage bound audit

This package is a read-only storage audit for the current F2/F3/F5 typed-conversion shapes. It reads the existing JSON reports and conversion/runtime source, and uses `stat` only for BI4/H5/CSV/DAT/VTK science paths. It does not open, hash, copy, launch, or mutate science payloads; it does not modify requests, receipts, the conversion lock, the ledger, or any controller.

## Findings

The direct converter allocates an HDF5 fixed identity axis with 40 bytes per particle per saved frame before filter and metadata effects, plus `8*frames + 13*particles` bytes for fixed arrays. The HDF5 datasets use LZF, but observed compressed sizes are diagnostic only and do not reduce the reservation.

The NVMe wrapper stages one conversion under `/tmp/ds02-nvme-conversion`, enforces a 24 GiB staged-output limit and a 100 GiB free-space reserve, then checksum-copies the staged H5 to a Home `.partial` file and publishes it with `os.replace`. PartVTK checks three frames sequentially; its CSV is deleted after each frame unless `keep_validation_csv` is set. The source has no byte cap for CSV or decoder auxiliary scratch, so a complete conservative bound for those transients cannot be proved from code alone.

At the audit snapshot, Home had 563,385,638,912 bytes free (524.69 GiB), leaving 24.69 GiB above the 500 GiB floor. Root854 reserves 32 GiB for the typed output and records a further 16 GiB wait margin. The typed request therefore cannot pass the live Home-floor guard at this snapshot, even though the observed H5 files are smaller. The current 24 GiB NVMe stage is on a separate filesystem with 481.25 GiB free and is not a reason to reduce the Home reservation.

The safe successor is metadata-only: preserve every existing request and receipt, wait for Root to release the old conversion reservation, then bind downstream XMF/bed/render work to already completed typed reports under the normal Root142 live check. No completed conversion should be repeated. A downstream 1 GiB estimate is eligible only after the conversion reservation is gone and the downstream worker itself proves that bound; this package does not start it.

## Representative stat-only inputs

- F2: 401 frames × 418,104 particles; logical uncompressed dataset bound 6,711,826,720 bytes; observed H5 stat 1,179,663,571 bytes.
- F3: 836 frames × 179,208 particles; logical uncompressed dataset bound 5,995,051,912 bytes; observed H5 stat 2,480,626,608 bytes.
- F5: 801 frames × 194,427 particles; logical uncompressed dataset bound 6,231,975,039 bytes; observed H5 stat 1,613,009,368 bytes.

The observed sizes are retained as diagnostics, not as admission limits. The validator checks that the package contains no independently computed science-payload hash.

## Validation

```bash
python3 -B scripts/validate_fresh153.py
```
