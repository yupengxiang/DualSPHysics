# F5 Stage 1 native initial fixed-bed support audit

This fresh scope prepares a bounded source-only worker for Root's strict
follow-up to the confirmed Root037 full801 crossing result.  It reads the
immutable original013 typed H5 only when Root authorizes the disabled request;
the committed checks do not open H5/BI4/CSV data, run GenCase or the solver, or
render a scene.

The future worker audits selected native frames 0 and 400 by default.  It
retains every valid Type-0 fixed row and records:

- valid/finiteness counts and sorted UID digests for all fixed rows and the
  generated XML `mk=40` bed cohort;
- native bed presence, mass, z, exact continuous-bed profile distance, and
  deepest UID samples;
- DP-sized x bins, all six exact continuous-bed x segments, and a near-mid-y
  strip `|y| <= 0.01 m`;
- optional native marker histograms and relative particle layers defined by
  `round((particle_z - bed_z(x)) / dp)`.

The canonical H5 identity is `(particle_zone, particle_id)`, where
`particle_zone` is the BI4 Piece namespace and is not an `mk` marker.  The
worker parses the generated XML `<particles>` `begin/count` ranges and maps
the fixed `mk=40` range into that namespace.  An actual marker dataset is
optional (`/mk`, `/initial_mk`, `/marker`, `/mkcode`, or `/marker_code`); when
it is absent, the XML-derived Type-0 support spatial map is retained and the
report marks native marker state as unknown.  The worker also compares the
actual H5 time dataset (`/time`, `/times`, or `/Time`) against all XDMF `Time`
entries at `1e-9 s`.  It fails on a time-axis mismatch instead of assigning
coordinates from XDMF alone.

`provenance.json` binds the source Def050, actual Gen050 generated XML and
generated Def050, prepared-input report, GenCase receipt and log, bed STL, and
motion asset.  The future worker verifies each hash, parses the XML draw mode,
triangle mesh declaration, `drawfilestl` and clip-plane metadata, summarizes
STL ASCII facet/bounds attributes, and preserves GenCase log warnings.  Static
generated counts remain provenance only; they are not native fixed-particle
counts.  The report explicitly declines a hollow-STL claim, solver root-cause
claim, repair, Q-N, or production approval.

The exact source geometry bound in the metadata is:

```text
(-0.2, 0.0), (2.0, 0.0), (3.0, 0.28), (3.6, 0.448),
(3.9, 0.448), (4.4, 0.05), (4.8, 0.05)
```

The request remains `launch_allowed=false`, `kind=cpu`, and
`cpu_task_kind=audit`; Root owns any future execution.

Source-only checks:

```bash
python3 scripts/native_initial_fixed_bed_support_audit.py --check
python3 -m pytest -q tests/test_native_initial_fixed_bed_support_audit.py
```

Both commands use only in-memory or temporary synthetic metadata.
