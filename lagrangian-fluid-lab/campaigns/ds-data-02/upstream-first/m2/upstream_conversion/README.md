# M4 official mDBC raw-to-normalized route

This subtree prepares the first M4 normalized data product for the unchanged
official v5.4 `mDBC/04_Dambreak/CaseDamBreak3D` source. The conversion engine is
the existing
[`ds_data02_direct_convert.py`](/home/jade/.codex/worktrees/upstream-first/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py).
The files here only stage a parent-bound temporal frame window, validate the
small conversion report, and describe the handoff to the existing portable
reader. They do not implement a BI4 or PartOut decoder.

The canonical source definition is the official file
`/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/examples/mdbc/04_Dambreak/CaseDamBreak3D_Def.xml`.
Its SHA-256 is
`1f7cca807e16a3b1a1cc4da649a68db5166439d3f4b30fa4ea25635baf6045b7`. The
checked-in owner metadata binds the same source, geometry, controls, and six
second physical source window:
[`official-mdbc-owner-metadata.json`](official-mdbc-owner-metadata.json).

The initial bounded conversion window is **0.0–1.6 s**. It covers release,
first obstacle interaction, and the downstream remerge target while avoiding a
second full six-second HDF5 materialization during the first storage tranche.
The parent can select another sub-window inside the physical 0–6 s source
window by changing the request and frame manifest. The worker copies or
hardlinks **every spatial particle** in every selected BI4 frame. It never
selects particle samples, changes `(Zone,Idp)`, or infers a material trajectory.

## Execution sequence

1. After the root solver receipt is complete, root creates a small
   `ds-data-02.m4.bi4-frame-manifest.v1` JSON file. It lists every selected
   `Part_*.bi4` file, its native time, byte size, and SHA-256. Building this
   manifest is a parent-scheduled metadata/native-input operation; this subtree
   does not scan the active solver output now.
2. Root runs
   [`bounded_conversion.py`](bounded_conversion.py). It verifies each manifest
   hash, stages a contiguous `Part_0000.bi4` sequence, and invokes the existing
   direct converter unchanged. Hardlinks are preferred on the NAS; `--staging-mode
   copy` makes the storage charge explicit when a copy is required.
3. The direct converter streams one frame at a time and writes the complete
   fixed identity axis plus `valid[t,(Zone,Idp)]`. It retains `initial_type`,
   `initial_mk`, `initial_mass`, per-frame native fields, and its initial and
   transient missing ledgers. Official PartVTK checks remain enabled at the
   first, middle, and final selected frames.
4. Root obtains a producer-native lifecycle sidecar from the existing official
   PartOut/RunPARTs path. The sidecar follows
   [`native-lifecycle-records.schema.json`](native-lifecycle-records.schema.json)
   and carries the native `reason`/`motive` for each `(Zone,Idp,time)` record.
   The route keeps those reasons as numerical-node censoring evidence. It never
   maps them to “left the fluid”, “hit a region”, or another physical fate.
5. Root runs [`validate_conversion_report.py`](validate_conversion_report.py)
   against the report, generated XML, owner metadata, source definition, and
   native sidecar. This is report/XML/JSON only; it does not read HDF5, BI4,
   PartOut, or RunPARTs payloads. It emits a compatibility manifest for the
   later portable build.

## Field and label contract

The normalized HDF5 is the existing direct-converter schema: `time`,
`particle_id`, `particle_zone`, `valid`, `position`, `velocity`, `density`,
`mass`, `pressure`, `type`, `mk`, `initial_type`, `initial_mk`, and
`initial_mass`. Geometry and controls are taken from the generated XML hashes
and the explicit owner physical binding; the official definition XML hash is a
separate source-lineage edge.

Labels use the native key `(particle_zone, particle_id)`. Source and
destination endpoint labels are valid only when the corresponding endpoint
mask is true. Rows with invalid or transiently absent numerical nodes remain in
the identity axis with `valid=false`, `observed_all_frames=false`, and an
explicit exclusion/censoring record. A destination region is `UNKNOWN` for an
invalid destination. It is never used as a proxy for physical fate.

The no-model evaluator must mask invalid endpoint pairs before computing
displacement or region checks. Identity permutation and field perturbation
negatives remain integrity checks; endpoint self-equality is not a scientific
transport score.

## Real gaps found before launch

The existing M2 `portable_bundle.py` is intentionally strict for its original
complete-ID candidate: `validate_bundle()` calls `_validate_trajectory(...,
require_complete=True)` and also expects all position/state values to be
finite. The official F1 mDBC solver already reports native particle-out events,
so blindly feeding this conversion to that path would either reject the bundle
or drop valid identity rows. The M4 compatibility manifest therefore records
the gap explicitly. A later portable build must add a validity-aware mode that
allows NaNs only where `valid=false`, carries the initial/transient/native
exclusion sidecars, and masks labels/evaluator calculations. That change is
separate from this bounded conversion request and must not alter the original
complete-validity M2 artifact.

The direct converter has no PartOut/RunPARTs argument. The native sidecar is
therefore a deliberate post-conversion binding point for the existing official
producer record path. Until it is present, the report audit status is
`blocked_missing_native_partout_binding`; no scientific or portable-package
claim is granted.

The route keeps the physical source window at 0–6 s while selecting 0–1.6 s
for the first materialization. A later window extension must be admitted by
the root storage tranche and produce a new attempt; it must not append frames
into this attempt.
