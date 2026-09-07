# R3 fixed immersed box force gauge

> Candidate-only evidence. `overall_acceptance_status` is deliberately `candidate_not_accepted`; a finite trace is not a physical acceptance.

## Geometry and force semantics

- Box: `0.2 x 0.2 x 0.2 m`, volume `0.008000 m^3`; bottom at `z=0.2 m`, water top `z=0.6 m`, floor gap `0.2 m`.
- Pre-registered pressure reference: `Fz=78.48 N` (`rho*g*V`), reference only.
- Gauge output is signed pressure interaction on selected fixed boundary particles; it excludes gravity, support reaction, and viscosity.
- Source-to-global mapping is read from generated XML, not inferred from the requested label alone.

## Source semantics evidence

- Gauge XML: `doc/xml_format/_FmtXML_Gauges.xml` (`force/target mkbound`).
- `JGaugeSystem::AddGaugeForce`: `src/source/JDsGaugeSystem.cpp:472-493`; it resolves `mkbound` through `JSphMk`, and accepts fixed/moving blocks.
- `JGaugeForce`: `src/source/JDsGaugeItem.cpp:1710-1988`; it sums only fluid pressure interactions and emits signed `forcex/y/z`.

## Runs

| control | status | GPU / UUID | attempt | `Fz` mean last 0.20 s (N) | reference error | stable | fields |
|---|---|---:|---|---:|---:|---|---|
| `fixed_box_dbc_gravity` | `completed` | `4` / `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9` | `20260907T115452.522560Z-ff512c2c` | `124.777` | `58.99%` | `False` | `True` |
| `fixed_box_dbc_zero_pressure` | `completed` | `4` / `GPU-74ce8a29-c3cd-1e50-a9b4-a2293f2335c9` | `20260907T115459.044639Z-6ddfcdaa` | `0.000` | `n/a` | `True` | `True` |

### `fixed_box_dbc_gravity`

- Force trace: `results/fixed_box_dbc_gravity/20260907T115452.522560Z-ff512c2c/force_timeseries.csv`; samples `160`, time `0.000000--0.795163 s`.
- Three-window signed `Fz` means: `124.777`, `110.697`, `116.350 N`; stability limit `3.924 N`.
- Source `mkbound=1` maps to generated global `Mk=18` with `729` fixed particles; solver log says `Floating=0`, `Moving=0`.
- Field snapshots: fixed body max identity-matched motion `0.000e+00 m`; Mk-filtered body counts `729/729`; fluid count constant `True`, mass delta `0.000e+00 kg`, penetration `0/0`.
- Initial pressure range: `0.000--5395.488 Pa`.

### `fixed_box_dbc_zero_pressure`

- Force trace: `results/fixed_box_dbc_zero_pressure/20260907T115459.044639Z-6ddfcdaa/force_timeseries.csv`; samples `160`, time `0.000000--0.795011 s`.
- Three-window signed `Fz` means: `0.000`, `0.000`, `0.000 N`; stability limit `0.500 N`.
- Source `mkbound=1` maps to generated global `Mk=18` with `729` fixed particles; solver log says `Floating=0`, `Moving=0`.
- Field snapshots: fixed body max identity-matched motion `0.000e+00 m`; Mk-filtered body counts `729/729`; fluid count constant `True`, mass delta `0.000e+00 kg`, penetration `0/0`.
- Initial pressure range: `0.000--0.000 Pa`.

## Interpretation

The zero-pressure control is a useful chain check: uniform `rhop0`, zero gravity, complete fields, fixed body and zero signed force are all observed.  The gravity DBC chain is executable and genuinely fixed, but its force windows are not stable and the late mean is about 59% above the analytical pressure reference.  It remains a diagnostic failure, not evidence that the DBC pressure resultant is physically valid.

No mDBC run was fabricated: this package contains only the two requested DBC controls.  The two bounded mDBC calibrations are explicitly recorded as `blocked_not_run` until their normals/ghost geometry is independently safe and audited.

| blocked calibration | status | reason |
|---|---|---|
| `fixed_box_mdbc_same_geometry` | `blocked_not_run` | No independently safe mDBC normals/ghost geometry path was established; no fake run. |
| `fixed_box_mdbc_refined` | `blocked_not_run` | No independently safe mDBC normals/ghost geometry path was established; no fake run. |
