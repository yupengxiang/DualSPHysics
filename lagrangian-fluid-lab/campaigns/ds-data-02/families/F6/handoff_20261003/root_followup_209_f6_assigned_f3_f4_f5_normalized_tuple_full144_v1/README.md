# Fresh209 F3/F4/F5 normalized tuple audit

This package extends the bounded spot audit to the 48 F3, 48 F4, and 48 F5
rows present in the fresh194 metadata registry.  It uses actual native
execution receipts and case-bound JSON/XML metadata.  It never opens or hashes
BI4, H5, CSV, DAT, VTK, or PNG payloads.  Producer-attested hashes remain
attestations; they are not recomputed here.

The two F3 P1000 endpoint rows use the fresh208 actual forcing producer join.
Their stale native request binding remains a separate role.  No numeric pitch
is inferred from the `P1000` label.  F3 rows whose source metadata lacks an
explicit pitch field remain `UNCERTAIN` rather than being filled from an ID.

F4 uses gap, x/y offset, speed, initial velocity, and geometry.  F5 uses
explicit amplitude/time-scale bindings where the earlier owner was thin, and
the owner tuple for rows with a complete case-bound owner.  Paths, IDs,
resolution, time windows, and view names are excluded from normalized tuple
values.  Collision groups are reported and must be empty for the validator to
pass; the audit is evidence of distinct source tuples, not numerical or
visual acceptance.  A producer receipt with status `running` is retained as
running/unknown and is never converted into completed evidence.

Run:

```text
python3 scripts/validate_full_tuple_audit.py metadata/f3-f4-f5-normalized-tuples-144.json
```

No case credit, Q-N/Q-E, precision, or solver-product claim is made.
