# R3 F6 E1 fixed submerged-body hydrostatic closure

This is an isolated candidate-only feasibility package. The E1 matrix was not
run because the existing mDBC geometry gate is not proven (792 fixed/moving
zero normals in the nominal coarse preflight), and the inspected DBC/mDBC XML
definitions still describe a floating body rather than a fixed body. The
historical mDBC solver also emits a Chrono collision warning, which is outside
the E1 scope.

Key outputs:

- `r3-f6-fixed-hydrostatic.md` — human-readable no-run decision;
- `r3-f6-fixed-hydrostatic.json` — machine-readable gate, provenance and
  acceptance state;
- `run-manifest.json` — six planned primary rows, all blocked, with the three
  additional fine rows locked;
- `raw-log-summary.json` / `raw-log-summary.md` — selected historical log
  lines and hashes;
- `gpu-preflight.txt` — UUID/memory snapshot for GPU indices 4–7 only.

Regenerate the package (no solver is launched):

```bash
python3 audit-feasibility.py
```

The package intentionally does not copy or modify official repository files;
all source XML, geometry and prior logs are referenced by path and SHA-256 in
the machine-readable report.
