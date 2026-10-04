# F5 Stage 1 H5/native-fluid bed-support y-footprint correction

This fresh scope preserves the immutable 056 source-only worker and corrects
its geometry denominator.  The 056 worker's finite-and-x-only distance was a
useful projection diagnostic, but it could include fluid outside the actual
bed y width (`[-0.15, 0.15] m`).  This 057 worker keeps that diagnostic under
the explicit `x_projection_*` names and adds an actual x/y bed-footprint
diagnostic for every one of the 801 frames.

For each valid native Type-3 row, the future Root-authorized worker retains:

- x-projection counts, mass and deepest UID samples for the exact x domain;
- bed-footprint counts, 1-DP (`0.02 m`) and 2-DP (`0.04 m`) bins, mass and
  deepest UID samples for exact x **and** y domains;
- separate outside-bed-y counts/fractions, including the portion inside the
  flume y domain, while retaining those rows in the native denominator;
- finite-position/mass status, UID digests, native extrema and all frame
  provenance.

The three standard x/z overlays retain finite valid Type-3 rows and use
distinct colors for inside-bed-y, outside-bed-y but inside-flume-y,
outside-flume-y, and outside-bed-x rows.  The overlay metadata records any
plot subsampling and nonfinite rows; the diagnostic never masks or drops a
valid native row from its report.

The worker reads an actual H5 time dataset (`/time`, `/times`, or `/Time`)
and compares all values with the XDMF `Time` entries at absolute tolerance
`1e-9 s`.  A mismatch fails the authorized worker before frame metrics are
reported, preventing XDMF-only coordinate provenance.

The exact compact runup bed nodes remain:

```text
(-0.2, 0.0), (2.0, 0.0), (3.0, 0.28), (3.6, 0.448),
(3.9, 0.448), (4.4, 0.05), (4.8, 0.05)
```

This commit is source-only.  It has not opened the bound H5/BI4/CSV arrays,
run a solver or converter, rendered ParaView or matplotlib output, or changed
any numerical source.  `request.json` is deliberately `launch_allowed=false`
and uses the supported static request template `kind=cpu` and
`cpu_task_kind=audit`; Root owns any later authorization.

Source-only checks use only small in-memory arrays:

```bash
python3 scripts/nativefluid_bed_support_diagnostic.py --check
python3 -m pytest -q tests/test_nativefluid_bed_support_diagnostic.py
```

Both commands avoid the bound H5, BI4, CSV, XDMF, STL and motion inputs.
