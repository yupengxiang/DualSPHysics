# F7 fresh077 converter-scope repair and Root142 adapter

This package repairs the metadata contract exposed by Root364 before any
conversion was launched. The 24 fresh074 owners put gravity_m_s2 below
physical_binding.controls and omitted the converter's required explicit
density_kg_m3 and mechanism_id fields. The existing
ds_data02_direct_convert._physical_condition_scope therefore rejected the
first case with:

physical_binding is missing explicit fields
['density_kg_m3', 'gravity_m_s2', 'mechanism_id'].

The repair is a new owner layer. It leaves fresh074 and fresh076 immutable,
copies the existing physical binding, moves gravity to the required top-level
field, adds the source XML values density_kg_m3=1000.0,
gravity_m_s2=[0,0,-9.81], and mechanism_id=moving_obstacle_exchange, then
calls the actual converter function for every case. The resulting corrected
scope digest is the canonical_physical_binding_sha256 used by future
conversion reports.

Three identities remain explicit:

* original_declared_canonical_binding_sha256 is the fresh074 historical owner
  value and is retained only as historical provenance.
* declared_source_hash is the fresh074 source-plan hash.
* corrected_converter_scope_sha256 is the digest returned by the actual
  converter scope function and is the only canonical hash used for downstream
  producer binding.

The package contains 24 disabled Root142-compatible typed requests. They
retain the full 601-frame, 70,179-particle, 3-D contract and the native mass
semantics from the source. They have no production, visual, Q-N, or precision
claim. metadata/source-validation-report.json records that the real converter
scope passed all 24 cases and that the existing Root142 runtime and strict
digest checks passed for all 24 requests.

After Root has an actual typed receipt and conversion report for a case, bind
one or more cases with the metadata-only adapter:

/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
  <fresh077>/scripts/bind_fresh077_actual_typed.py
  --source-package <fresh077>
  --case-map /path/to/root-produced-case-map.json
  --output-dir /tmp/ds02-f7-fresh077-actual-bound

Each case-map row contains case_id, typed_receipt, and conversion_report. The
adapter reads only bounded JSON metadata and uses conversion-report.json
output_sha256 as a producer-attested trajectory digest. It checks the native
075 receipt metadata, corrected physical scope, 601/70,179/3-D counts, PartVTK
producer flag, and exact input-file/hash closures. It does not open, hash, or
decode H5/BI4/CSV/DAT payloads. It writes disabled XMF and Root023 render
bindings under the output directory, with independent xdmf and render output
directories and all future output hashes null. Root must review and explicitly
enable those requests.

The package is source-only: no solver, converter, XMF, renderer, scientific
payload, shared registry, or ledger was touched.

