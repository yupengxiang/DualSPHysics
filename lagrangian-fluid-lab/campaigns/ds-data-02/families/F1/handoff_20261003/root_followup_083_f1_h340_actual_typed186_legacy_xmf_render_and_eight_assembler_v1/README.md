# F1 fresh083: H340 legacy-aware audit XMF/render and eight-case assembler

This source-only handoff adds the two actual Root186 typed DUAL H340 cases:

- `F1_STAGE1_DUAL_H340_DP020_VX010`
- `F1_STAGE1_DUAL_H340_DP020_VX020`

Both cases have metadata receipts for Root162 GenCase `completed/0`, Root164
full native `completed/0`, Root181 saved-frame-0 VX audit `completed/0/pass`, and
Root186 typed conversion `completed/0`. Each is 3-D, 401 saved frames, and
130316 native particles. Native identity and mass are retained by the typed
worker; no continuum or CSV rescaling is claimed.

`metadata/legacy-canonical-sidecars/` records the semantic split required for
each H340 case. The converter report's
`hash_scopes.physical_condition_sha256` remains the legacy-owner-scope.v0 hash
that Root193 must compare with the runtime HDF5 attribute. The canonical
physical identity remains the fresh079 source owner's normalized
`physical_binding` JSON hash. The sidecar asserts that the two scopes are
separate and makes no Q-N or cross-resolution precision claim. The source turn
adopts the typed H5 producer hash from the actual conversion report's
`output_sha256`; it does not read or rehash H5.

The four request files are disabled Root193/Root194 audit requests. They use
CPU2 with `cpu_task_kind: audit`, keep all input file/hash keys closed, and use
separate output subdirectories so the strict runtime receipt can occupy the
attempt root safely:

- Root193 exporter: `--output-dir {attempt_root}/xdmf`
- Root194 Native023 renderer: `--output-dir {attempt_root}/render`

Root193 must complete with the full 401-frame XMF/manifest before Root194 is
enabled. The Native023 renderer scans valid native positions over every actual
saved XDMF time; it does not use a fixed camera/domain bound. Future XMF,
render, and receipt hashes are null and visual/production approval remains
pending Root review.

`metadata/eight-case-inputs.json` is a closed metadata index for the six
immutable fresh082 typed cases plus these two H340 cases. The
`workers/assemble_eight_root193_root194.py` script validates all eight owner,
GenCase, native, Root181, typed report, and request chains using JSON/XML/source
metadata only. It takes each actual conversion report's `output_sha256` as the
H5 producer hash and skips H5/BI4/CSV/VTK reads. By default it emits disabled
request copies:

```text
python3 workers/assemble_eight_root193_root194.py \
  --output-dir /path/to/assembler-output \
  --include-render
```

After Root has independently adopted the package, Root may provide an adoption
receipt with this exact JSON contract and request enabled copies:

```json
{"schema":"ds02.f1.root-adoption.v1","status":"accepted","owner":"root"}
```

```text
python3 workers/assemble_eight_root193_root194.py \
  --output-dir /path/to/assembler-output \
  --enable --root-adoption-receipt /path/to/root-adoption.json \
  --include-render
```

The assembler only writes request metadata; it never invokes a runner,
converter, solver, XMF exporter, or ParaView. The package validator is:

```text
python3 validate_source_contract.py
```

Validation result is metadata-only: two new H340 cases, four disabled local
requests, an eight-case closed assembler index, no arrays read, no jobs
started, and legacy/canonical layers separate. No GenCase, solver, converter,
XMF, ParaView, shared registry, or ledger task was launched by fresh083.
