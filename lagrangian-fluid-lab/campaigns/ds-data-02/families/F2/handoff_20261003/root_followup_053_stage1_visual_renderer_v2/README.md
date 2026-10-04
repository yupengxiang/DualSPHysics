# F2 stage1 full-animation renderer v2

This scope contains a reusable, source-only ParaView renderer for an existing
DS-DATA-02 temporal XDMF entry.  The entry and its HDF5 payload remain the
immutable source of positions, particle identities, native type values, and
all saved times.  The renderer adds display filters only:

* `valid == 1` is the active display mask;
* native fluid, moving, and floating type aliases are displayed as blue,
  orange, and red points respectively;
* the fixed boundary branch shows the actual native fixed points in gray with
  modest opacity, plus an optional outline, through one fixed y-mid-plane
  cutaway; the XDMF reader itself remains complete;
* moving and floating marker displays use that same display-only cutaway so
  dense cup points do not hide the fluid, while their full native proxies stay
  in the PVSM graph;
* two automatically bounded parallel cameras project all eight world-bound
  corners per view and use a restrained 12% margin with the real viewport
  aspect ratio;
* every selected saved frame gets a PNG, 24-frame contact sheets, and a GIF;
* per-frame finite-field, valid-count, native-type-count, and
  `(particle_zone, particle_id)` identity diagnostics are written to
  `paraview-full-animation-report.json`.

The script imports ParaView and VTK only when rendering, so ordinary Python
checks can audit the manifest and camera API without a ParaView ABI.  It does
not import an HDF5 library, run a solver, run GenCase, read CSV/BI4 arrays, or
claim visual or numerical acceptance.  The root dispatcher owns all actual
ParaView launches and review decisions.

## Root launch contract

Use a newly allocated output directory and the exact manifest produced by the
immutable temporal XDMF exporter:

```text
pvpython render.py \
  --manifest /absolute/path/to/manifest.json \
  --output-dir /absolute/path/to/new-render-entry
```

Before the full render, root may run a bounded display diagnostic such as:

```text
pvpython render.py \
  --manifest /absolute/path/to/manifest.json \
  --output-dir /absolute/path/to/new-diagnostic-entry \
  --diagnostic-frames 0,200,400
```

The diagnostic output is explicitly marked `diagnostic_only` and
`visual_review: pending`; it does not count as a visual pass.  A full run
must use the default selection, which renders every XDMF saved frame.

The manifest may provide `type_codes` or `type_aliases` with native integer
codes for `fixed`, `moving`, `floating`, and `fluid`.  The default DualSPHysics
aliases are `{fixed: 0, moving: 1, floating: 2, fluid: 3}`.  Optional
`camera_bounds` or `domain_bounds` are accepted as a bound from the source
ledger.  If neither is present, the renderer scans the valid native points
through the XDMF reader and computes a stable bound without clipping the
source.

`request.template.json` is a root-bindable placeholder only.  Its `cases`
array must be filled from root-reviewed manifests and exact source hashes;
the template is not a launch receipt and contains no numerical case result.
