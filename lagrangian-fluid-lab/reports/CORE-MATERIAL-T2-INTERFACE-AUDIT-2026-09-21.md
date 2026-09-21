# Core material T2 interface audit — 2026-09-21

This CPU-only audit reviewed `scripts/core_material.py`,
`scripts/core_material_acceptance.py`, the F3/F4 material manifests and
checkpoint sidecars under `campaigns/core-v1/material/evidence`, and the
material denominators reported by `scripts/core_campaign.py`.

The actionable gap was in the F4 material schema boundary.  F4 traces already
persist `source_membership` and `destination_membership`, derived from the
bound seed geometry and `f4_definition.q`, but resume validation and the H5
acceptance audit only checked that those datasets existed.  Both paths now
recompute the memberships from the immutable binding and reject missing,
wrongly typed, wrongly shaped, or changed arrays.  This closes a resume and
artifact-integrity gap without changing any material denominator or T2 gate.

The campaign denominator review found the intended distinction: the target
material denominator remains 288 case runs, while the registered-material
denominator remains zero until a material scope is explicitly admitted.  No
`core_campaign.py` change is required.  Existing F3/F4 sidecars remain
diagnostic and right-censor aware; no smoke or profile artifact is promoted to
T2, and no registry, ledger, or matrix mutation is performed.

Focused validation:

```text
.venv/bin/pytest -q tests/test_core_material.py \
  tests/test_core_material_acceptance.py tests/test_core_campaign.py
37 passed in 3.60s
```

No solver, GPU, queue, or CFD job was started.
