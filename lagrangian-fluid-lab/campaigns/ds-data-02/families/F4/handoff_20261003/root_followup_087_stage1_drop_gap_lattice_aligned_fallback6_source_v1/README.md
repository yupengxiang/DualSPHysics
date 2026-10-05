# F4 fresh087 lattice-aligned fallback six

Root216 is preserved as a real failed native initial-QA attempt.  Its eight
half-dp gap candidates passed finite/UID/3-D/count/mass/nonoverlap/tank-face
checks but failed `exact_center_lattice`, `complete_cell_population`, and
`strict_continuum_center_bounds`.  This package therefore adds six distinct
source-only candidates at gaps `0.190, 0.200, 0.210, 0.230, 0.240, 0.250 m`.

Each Definition is byte-derived from the frozen centered mother and changes
one attribute only: the falling-drop point z.  The source contract records
the aligned phase as `point_z = gap + 0.205` and source-region lower z as
`gap + 0.200` at `dp=.01`.  Pool, wall/tank, drop x/y/size/velocity, physics,
and the `1.2 s / .001 s / 1201-frame` recipe are unchanged.  Owners and
metadata keep native counts and native mass null; the planned lattice counts
are explicitly reference-only and must be replaced by actual generated XML
and QA evidence.

The six GenCase requests, six native initial-QA requests, and six disabled
full1201 requests all have `launch=false`, `launch_allowed=false`,
`launch_owner=root`, and future hashes null.  Root should enable each
GenCase source independently, bind the actual per-case XML/BI4/receipt, and
then run `workers/run_f4_fallback_native_initial_qa_v1.py`.  That worker uses
the official read-only Posd/Idp audit and XML/UID-derived marker partition;
it refuses source-side BI4 hashing and does not rerun GenCase.  Full1201
solver requests remain disabled until the actual native QA for the matching
physical binding passes.

The producer also has a metadata-only preflight for Root review:

```text
python3 workers/run_f4_fallback_native_initial_qa_v1.py --metadata-preflight \\
  --plan source-plan.json --owner-root owners --output-root /tmp/ds02-f4-fallback6-metadata-preflight \\
  --gencase-binding /tmp/unused --audit-script /path/to/ds_data02_f4_centered_reference_v1.py \\
  --python /usr/bin/python3
```

That preflight completed all six source bindings with `native_counts=null`,
`native_mass=null`, and `arrays_read=false`; it does not substitute for later
genuine GenCase and native QA receipts.

No GenCase, native solver, converter, renderer, scientific-array read, shared
registry write, or ledger update was performed while preparing this package.
