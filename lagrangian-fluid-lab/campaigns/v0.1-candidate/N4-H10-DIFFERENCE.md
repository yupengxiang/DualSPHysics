# N4 h10 difference analysis

Baseline: `d721473f524c71bd85ba88064f66026de8306989`

## Primary peak

- Registered requested time: `1.05 s`
- Registered grid index: `14`
- Max coarse→medium TV: `0.056904761904761875`
- Gate: `0.05`
- Grid classification: `registered_grid_localized_peak`

| region | coarse mass fraction | medium mass fraction | medium − coarse |
|---|---:|---:|---:|
| `downstream_high_y_ge_0p2` | 0.30642857142857144 | 0.36333333333333334 | 0.0569047619047619 |
| `downstream_low_y_lt_0p2` | 0.3657142857142857 | 0.3597619047619048 | -0.005952380952380931 |
| `intermediate_or_corridor` | 0.0 | 0.0 | 0.0 |
| `unclassified_or_lost` | 0.0 | 0.0 | 0.0 |
| `upstream_x_lt_0p58` | 0.32785714285714285 | 0.27690476190476193 | -0.050952380952380916 |

## Interpretation

The peak is localized on the registered diagnostic grid, but this does not prove a transient-only cause. Initial mass/discretization and CFL=0.2 vs CFL=0.1 are reported as diagnostics; neither is used to rewrite the primary gate. Alternative smoothing, phase alignment, or region boundaries cannot replace the registered comparison.

The full numerical series and same-resolution CFL sensitivity are in `N4-H10-DIFFERENCE.json`.
