# M4 normalized upstream adapter

This subtree owns the M4 handoff producer and consumer. The producer consumes a
completed standard HDF5 and report from `scripts/ds_data02_direct_convert.py`,
the generated XML and owner metadata, and verified native-integrity/full-frame
scan receipts. It creates a separate enriched HDF5 copy with `/native` and
`/transport` datasets. It opens the direct-converter artifact read-only and
never patches it, decodes BI4, inspects PartOut, invokes a solver, or replaces
the converter owned by `m2/upstream_conversion`.

The handoff contract is
[`native-conversion-interface.schema.json`](native-conversion-interface.schema.json).
The producer supplies relative `normalized_hdf5`, `geometry`, and `control`
bindings, the fixed full `(Zone,Idp)` identity contract, a native exclusion
mask, endpoint datasets, and source receipt hashes. The adapter copies the
normalized HDF5 with
path-bearing attributes redacted. Source receipt roles and hashes remain in
the portable interface, while host paths are replaced by receipt labels.
The resulting bundle also carries a copied, read-only `l2_reader.py` and an
L2 canonical reader manifest. The M4 validity and endpoint checks remain the
authoritative acceptance checks; the bundled reader supplies the same
relocatable frame access architecture used by M2.

The normalized HDF5 keeps the full initial typed identity axis on every frame:

* root fields follow the direct conversion names `time`, `particle_id`,
  `particle_zone`, `valid`, `position`, `velocity`, `density`, `mass`,
  `pressure`, `type`, `mk`, `initial_type`, `initial_mk`, and `initial_mass`;
* `/native/exclusion_mask` is a one-dimensional mask over the initial Idp
  axis. A verified mask must equal the final missing identity set. Its count
  and Idp hash are bound in the interface;
* `/transport` contains identity copies, source/destination validity masks,
  endpoint labels, endpoint positions, and displacement. Valid endpoints use
  `valid_source` or `valid_destination`. Missing endpoints use only `unknown`
  or `censored`; displacement is NaN when either endpoint is missing.

The validator checks all frame fields at their fixed identity positions. It
binds both Zone and Idp with a canonical typed-axis hash, checks the explicit
validity mask across every frame, and requires geometry/control sidecars with
actual coordinate-frame and event-window evidence. A
non-finite value is allowed only where that field's `valid` mask is false.
Initial identity fields, time, and valid endpoint values must be finite. It
rejects duplicate typed identities, mask/hash disagreement, endpoint identity
permutations, label/mask mismatches, fabricated fate labels, and finite
displacements for missing endpoint pairs.

For the M3 depth children, the producer derives a child owner record before
direct conversion. It binds the evaluated generated XML, M3 case manifest, and
semantic diff to a depth-specific `physical_binding` hash. The generated XML's
obstacle and fillbox values replace the legacy mother-card separator range;
the rounded fillbox is retained as explicit generated evidence. H050 and H060
request templates are in [`requests/`](requests/), and both remain
`prepared_not_run` until the root-controlled solver, native audits, and storage
gates are complete.

`m4-condition-template.json` records the bounded F1 mapping. It preserves the
known native exclusion counts of **657** for the official mother and **382**
for the DP015 numerical bridge. DP010 H050/H060 remain `pending_audit` with
unknown exclusion counts. The bridge is explicitly a same-physical-mother
numerical bridge and receives no physical-condition or equivalence credit.
All four rows are prepared templates and carry `not_credited`; preparation is
not an M4 product acceptance claim.

## Commands

Prepare a child owner record before invoking the direct converter:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_direct_enrich.py prepare-owner \
  --owner-metadata /path/to/official-mother-owner.json \
  --generated-xml /data/nas/.../UF_F1_MDBC_DP010_H050.xml \
  --case-manifest /path/to/UF_F1_MDBC_DP010_H050.json \
  --semantic-diff /path/to/semantic-diff.json \
  --output /data/nas/.../child-owner-metadata.json
```

After the direct converter and both native audits have completed, create the
new enriched copy and interface:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_direct_enrich.py enrich \
  --trajectory /path/to/direct/trajectory.h5 \
  --report /path/to/direct/direct-conversion-report.json \
  --generated-xml /data/nas/.../generated-child.xml \
  --owner-metadata /data/nas/.../child-owner-metadata.json \
  --native-integrity /data/nas/.../native-integrity-001/integrity.json \
  --frame-scan /data/nas/.../native-frame-scan-001/frame-identity-scan.json \
  --case-manifest /path/to/child-case-manifest.json \
  --semantic-diff /path/to/semantic-diff.json \
  --output-dir /data/nas/.../m4-enriched
```

Validate a producer handoff, without creating a bundle:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_portable_adapter.py validate-interface --interface /path/to/interface.json
```

Build a relocatable bundle around the already-normalized HDF5:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_portable_adapter.py build --interface /path/to/interface.json \
  --output /path/to/m4-bundle
```

Run the bundle validator directly or in the source-denying bubblewrap
wrapper:

```sh
/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_portable_adapter.py validate --bundle-root /path/to/m4-bundle

/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  m4_isolated_validate.py --bundle-root /path/to/m4-bundle \
  --python /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python \
  --output /path/to/m4-validation.json
```

The tests build only a tiny synthetic normalized package. They cover valid
NaN masking, non-finite valid values, full typed-axis identity, native mask
binding, endpoint semantic negatives, geometry/control evidence, bundle
relocation, three actual metadata tamper negatives, and the optional
bubblewrap wrapper. No scientific payload or upstream converter is read by
the tests.
