# F7 fresh072: Root310/313 actual native to typed/XMF/render handoff

This F7-only package binds the 16 first24 cases to the actual Root310 initial QA aggregate and Root313 full601 native receipts. The source snapshot observed all 16 native attempts as `completed` with returncode 0. The 48 downstream requests remain disabled for Root review and Root142 CPU conversion admission.

Each case preserves the source plan condition hash, canonical physical-binding hash, amplitude, source definition/module hashes, and the producer motion SHA from `prepared-input-report.json`. Actual counts are carried as producer metadata: total 70179, fixed 27495, moving 1984, fluid Type 3/Mk 2 count 40700, floating 0, dimension 3. Native fluid mass 325.60001628 kg and the 320.1984 kg continuum envelope remain separate and are never rescaled.

The typed requests reuse the approved L/.venv NVMe wrapper, BASE decoder, PartVTK validator, Root142 profile, two conversion slots, 100 GiB free floor, 32 GiB output estimate, and 24 GiB staging cap. XMF and Root023 requests use independent `xdmf` and `render` child directories. Their vector contract is explicit: `outshape = shape[1:]`, `N 3` for vectors, `N` for scalars, and all 601 saved frames with automatic native bounds. `producer_scope_schema` is present as `ds-data-02.physical-binding.v1`; source-plan and canonical hashes remain distinct.

No BI4, CSV, H5, or motion payload is included or read by this package. The motion SHA is adopted from the registered GenCase JSON report. No solver, conversion, XMF, render, ledger, registry, or shared state was started or changed.

Run the source-only checks from the F7 worktree:

```text
python scripts/preflight_fresh072.py --root . --write-report
```

`metadata/source-validation-report.json` records 48/48 disabled requests, closed input/hash sets, no raw payload inputs, and no job side effects. `scripts/post_typed_fresh072.py` is a metadata-only staging helper for a later actual typed receipt; it adopts the producer H5 SHA from the conversion report without opening H5 bytes and writes an enabled staging copy outside the immutable disabled request.
