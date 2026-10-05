# F5 fresh102 explicit physical binding and disabled stage chain

This package fixes the fresh101 interface gap by supplying a real, converter-validated `ds-data-02.physical-binding.v1` object for each bounded control candidate:

- A080: canonical converter scope `68b99ef9d44f0c3a5a999982c3accd8bfc3f31f03af79896cbc4b9c414919b9e`
- A120: canonical converter scope `6d02cb6e30b62cb881b372f61b6458919544a33ce8a6cfcd5367aab9c1d366a5`

The binding contains only the continuous physical contract accepted by the real integration converter: the closed analytic bed and finite tank geometry, still-water initial state, gravity and density, solver control semantics, event window, and the registered motion source plus candidate amplitude scale. It omits DP, save cadence, particle counts, lattice tolerances, and future output hashes. The builder calls the actual `ds_data02_direct_convert._validate_physical_binding`, `_physical_condition_scope`, and `canonical_hash` functions; `preflight_fresh102.py` repeats that check.

The package keeps identities separate. The fresh099 owner identity and owner-file SHA, candidate Definition/source-plan SHA, fresh090 canonical recipe SHA, Gen293 legacy producer scope `3cd1ce...`, and the new explicit converter scope are recorded as different roles. The actual Gen293 values 194427 total, 158559 fixed, 4210 moving, 0 floating, 31658 fluid and 3-D are baseline provenance only. A080/A120 candidate counts stay null until their own producer receipt; no baseline count is used as an expected candidate result. The motion DAT digest is copied only from registered producer metadata; this source package did not read or hash DAT, BI4, CSV, H5, XMF or VTK payloads.

Each candidate has five disabled, Root-owned request templates: motion transform, genuine GenCase, producer-bound initial QA plus native Mk50 coverage, a 1 s/51-frame native qualification run, and the framewise dynamic bed audit. The short native request requires the actual GenCase prepared directory as cwd so the relative scaled motion asset resolves. GenCase semantic fields require actual producer values for total/fluid/type counts and `data2d=false`; all are null before execution. The bed audit retains native Mk50/source Mk40, the exact x and y footprint, all saved states, full initial-fluid UID denominator, finite/lost UID reporting, and unchanged 1DP/2DP diagnostics. It does not authorize full801 or relax the old numerical precision threshold.

All requests are `disabled=true`, `launch=false`, `execution_allowed=false`, `solver_allowed=false`, `conversion_allowed=false`, `arrays_allowed=false`, and carry Root resource/lease metadata. Native qualification carries the reviewed Root230 Home-floor/GPU wrapper identity and 4096 MiB peak estimate; CPU stages retain the Root142 CPU dispatch provenance. No job, converter, registry, ledger, or shared integration state was changed.

Root370 proves that the original piston trajectory executed, while Root402/408 still quantify a weak, unproven runup mechanism. The legal 0.8 and 1.2 controls are bounded hypotheses, not acceptance evidence. Full801, Q-N, case credit, and all future hashes remain disabled/null until each actual short chain and visual review succeeds.

Run from the integration venv:

```text
/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python scripts/preflight_fresh102.py
```

The next Root review/registration entry points are the ten JSON files under `requests/`, beginning with each `*-motion-transform-request.json` and advancing only after actual upstream receipts are bound.
