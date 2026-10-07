# Fresh207 cross-family physical distinctness spot audit

This is a bounded, source-only sidecar for the parent fresh194 physical
distinctness review.  It checks two F3 endpoint bindings, three F4 cases, and
five F5 motion cases using JSON and XML/XMF metadata only.  It does not open or
hash BI4, H5, CSV, DAT, VTK, or PNG payloads, and it does not launch a job.

The F3 result is deliberately a mismatch.  Root007's lower and upper source
bindings carry transverse amplitudes 0.25 and 0.75, but no numeric pitch field
is present (P1000 remains a reference label, not a numeric assertion).  Both
actual native requests and both endpoint XMLs resolve to the nominal AY0P50
single-axis input, with request amplitude 0.5 and the same XML SHA.  These
products cannot establish the requested endpoint distinction.

The selected F4 normalized tuples contain gap, x/y offset, drop speed,
initial velocity, and geometry.  Case identifiers, paths, resolution, time
window, and view names are excluded.  The three selected tuples are unique;
this is a spot check and does not certify the full family.

The selected F5 values come from explicit physical-binding JSON and the
producer motion-transform reports.  A080/A120 retain a genuinely absent
`time_scale`; the source report's amplitude scale is recorded without
inventing a time scale.  M085/T090, M115/T080, and M115/T100 retain their
explicit amplitude/time scales.  The thin owner metadata from fresh194 is
kept as a separate draft role and never used to overwrite the explicit source
binding.

Run the package validator with:

```text
python3 scripts/validate_spot_audit.py metadata/physical-distinctness-spot-audit.json
```

The package carries no acceptance or numerical precision credit.  Historical
source bytes and actual execution receipts remain in their producer paths.
