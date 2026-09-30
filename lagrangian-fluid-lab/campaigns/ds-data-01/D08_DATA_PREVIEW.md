# DS-DATA-01 compact data preview

This preview is metadata-only. It does not claim external scientific validation or material lineage.

## Coverage

- D02 atlas: 26 cases across 7 families.
- D03 Q-I structure pass: 25 cases.
- D05 internal cases: 8 (7 Solver conversions with Q-I structure pass).
- D04 production assignments: train=0, validation=0, test=0.

## Family view

| Family | Atlas cases | Roles | Representative | Mechanism |
|---|---:|---|---|---|
| F1 | 2 | candidate_pending_D03=2 | `F1_main_dambreak3d` | 3D single-phase dam-break free-surface propagation anchor |
| F2 | 12 | candidate_pending_D03=5, diagnostic=7 | `W06_narrow_far_partial` | derived rotating-cup pour/catch |
| F3 | 2 | candidate_pending_D03=2 | `O3_sloshing_acc` | accelerated-frame-sloshing |
| F4 | 2 | diagnostic=2 | `F4_shapes_inlet3d` | 3D shapes inlet liquid-column collision anchor |
| F5 | 3 | candidate_pending_D03=2, exclusion_negative=1 | `O5_solitary_wave` | solitary-wave-propagation |
| F6 | 3 | candidate_pending_D03=2, diagnostic=1 | `O6_falling_wedge_vres` | variable-resolution-water-entry |
| F7 | 2 | calibration=1, candidate_pending_D03=1 | `F7_moving_square2d` | 2D prescribed moving obstacle control contrast |

## D05 case view

| Case | Family | Frames | Identities | Initial → final | Retention | Q-I | HDF5 | Role |
|---|---|---:|---:|---:|---:|---|---:|---|
| `B05_F1_main_dambreak3d_dp030` | F1 | 7 | 2730 | 2730 → 2730 | 1.0000 | Q-I-structure-pass | 0.5 MiB | candidate |
| `B05_F1_mdbc_dambreak3d_dp030` | F1 | 7 | 21760 | 21760 → 21760 | 1.0000 | Q-I-structure-pass | 3.3 MiB | candidate |
| `B05_F2_w06_candidate_bundle` | F2 | — | — | — → — | — | reference_reuse_only | reuse | candidate |
| `B05_F3_sloshing_motion_dp030` | F3 | 11 | 58 | 58 → 58 | 1.0000 | Q-I-structure-pass | 0.0 MiB | candidate |
| `B05_F4_shapes_inlet3d_dp030` | F4 | 5 | 18042 | 2328 → 18042 | 1.0000 | Q-I-structure-pass | 1.2 MiB | diagnostic |
| `B05_F5_solitary_wave_kdv_dp030` | F5 | 11 | 4576 | 4576 → 4576 | 1.0000 | Q-I-structure-pass | 0.9 MiB | candidate |
| `B05_F6_floating_box_dp030` | F6 | 9 | 13577000 | 13577000 → 13577000 | 1.0000 | Q-I-structure-pass | 2814.3 MiB | candidate |
| `B05_F7_pump3d_dp030` | F7 | 7 | 1401 | 1401 → 1389 | 0.9914 | Q-I-structure-pass | 0.3 MiB | candidate |

## Reading rules

- `Q-I-structure-pass` is a numerical storage/schema gate, not an external scientific validation result.
- `introduced_after_initial` and `initial_missing_at_final` are shown to expose open lifecycle and numerical loss behavior.
- All D05 cases remain `internal_development_only` and `unassigned`; no train/validation/test release is implied.
