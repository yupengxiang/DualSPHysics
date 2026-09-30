# DS-DATA-01 geometry and control index

This index preserves geometry/source lineage and explicit batch controls. It is metadata-only; it does not reconstruct geometry or infer material lineage.

## D05 batch recipes

| Case | Parent | Family | Role | Source | Base | dp | tmax | tout | Action | GPU |
|---|---|---|---|---|---|---:|---:|---:|---|---:|
| `B05_F1_main_dambreak3d_dp030` | `F1_main_dambreak3d` | F1 | candidate | `main/01_DamBreak` | `CaseDambreak` | 0.03 | 0.6 | 0.1 | solver_reproduction | 1 |
| `B05_F1_mdbc_dambreak3d_dp030` | `F1_mdbc_dambreak3d` | F1 | candidate | `mdbc/04_Dambreak` | `CaseDamBreak3D` | 0.03 | 0.6 | 0.1 | solver_reproduction | 2 |
| `B05_F2_w06_candidate_bundle` | `W06_narrow_fast_center;W06_narrow_slow_center;W06_standard_fast_center;W06_standard_slow_center;W06_wide_slow_center` | F2 | candidate | `campaigns/v0.1-candidate/data/w06` | `—` | — | — | — | reference_reuse_only | reuse |
| `B05_F3_sloshing_motion_dp030` | `O3_sloshing_motion` | F3 | candidate | `main/05_SloshingTank` | `CaseSloshingMotion` | 0.03 | 1.0 | 0.1 | solver_reproduction | 3 |
| `B05_F4_shapes_inlet3d_dp030` | `F4_shapes_inlet3d` | F4 | diagnostic | `inletoutlet/05_ShapesInlet3D` | `CaseShapesInlet3D` | 0.03 | 0.4 | 0.1 | solver_reproduction | 4 |
| `B05_F5_solitary_wave_kdv_dp030` | `O5_solitary_wave` | F5 | candidate | `main/16_SolitaryWaves` | `CaseSolitaryWave_KdV` | 0.03 | 1.0 | 0.1 | solver_reproduction | 5 |
| `B05_F6_floating_box_dp030` | `O6_floating_box` | F6 | candidate | `main/11_Floating` | `CaseFloating` | 0.03 | 0.8 | 0.1 | solver_reproduction | 6 |
| `B05_F7_pump3d_dp030` | `F7_official_pump3d` | F7 | candidate | `main/13_Pump` | `CasePump` | 0.03 | 0.6 | 0.1 | solver_reproduction | 7 |

## Lineage controls

| Case | Geometry ID | Mechanism ID | Source lineage | Parameter lineage | Resolution complete | Split |
|---|---|---|---|---|---|---|
| `F1_main_dambreak3d` | `geometry:source:main_01_dambreak` | `mechanism:F1:3d_single_phase_dam_break_free_surface_propagation_anchor` | `source:official_canary_reproduction:main_01_dambreak` | `parameter:case:f1_main_dambreak3d` | False | unassigned |
| `F1_mdbc_dambreak3d` | `geometry:source:mdbc_04_dambreak` | `mechanism:F1:3d_mdbc_dam_break_obstacle_reconnection_anchor` | `source:official_canary_reproduction:mdbc_04_dambreak` | `parameter:case:f1_mdbc_dambreak3d` | False | unassigned |
| `F4_shapes_inlet3d` | `geometry:source:inletoutlet_05_shapesinlet3d` | `mechanism:F4:3d_shapes_inlet_liquid_column_collision_anchor` | `source:official_canary_reproduction:inletoutlet_05_shapesinlet3d` | `parameter:case:f4_shapes_inlet3d` | False | unassigned |
| `F7_moving_square2d` | `geometry:source:main_03_movingsquare` | `mechanism:F7:2d_prescribed_moving_obstacle_control_contrast` | `source:official_canary_reproduction:main_03_movingsquare` | `parameter:case:f7_moving_square2d` | False | unassigned |
| `F7_official_pump3d` | `geometry:source:main_13_pump` | `mechanism:F7:3d_prescribed_rotating_pump_transport_anchor` | `source:official_canary_reproduction:main_13_pump` | `parameter:case:f7_official_pump3d` | False | unassigned |
| `O3_sloshing_acc` | `geometry:source:main_05_sloshingtank` | `mechanism:F3:accelerated_frame_sloshing` | `source:official_historical_reuse:main_05_sloshingtank` | `parameter:case:o3_sloshing_acc` | False | unassigned |
| `O3_sloshing_motion` | `geometry:source:main_05_sloshingtank` | `mechanism:F3:prescribed_moving_tank` | `source:official_historical_reuse:main_05_sloshingtank` | `parameter:case:o3_sloshing_motion` | False | unassigned |
| `O4_impinging_jet` | `geometry:source:inletoutlet_08_impingingjet` | `mechanism:F4:open_boundary_impinging_jet` | `source:official_historical_reuse:inletoutlet_08_impingingjet` | `parameter:case:o4_impinging_jet` | False | unassigned |
| `O5_solitary_wave` | `geometry:source:main_16_solitarywaves` | `mechanism:F5:solitary_wave_propagation` | `source:official_historical_reuse:main_16_solitarywaves` | `parameter:case:o5_solitary_wave` | False | unassigned |
| `O5_wave_runup` | `geometry:source:main_17_waverunup` | `mechanism:F5:wave_runup_moving_piston` | `source:official_historical_reuse:main_17_waverunup` | `parameter:official:main_17_wave_runup` | False | unassigned |
| `O5_wave_runup_refined` | `geometry:source:main_17_waverunup` | `mechanism:F5:wave_runup_moving_piston` | `source:official_historical_reuse:main_17_waverunup` | `parameter:official:main_17_wave_runup` | False | unassigned |
| `O6_falling_wedge_vres` | `geometry:source:vresolution_04_fallingwedge2d` | `mechanism:F6:variable_resolution_water_entry` | `source:official_historical_reuse:vresolution_04_fallingwedge2d` | `parameter:case:o6_falling_wedge_vres` | False | unassigned |
| `O6_floating_box` | `geometry:source:main_11_floating` | `mechanism:F6:free_floating_body_six_dof` | `source:official_historical_reuse:main_11_floating` | `parameter:case:o6_floating_box` | False | unassigned |
| `O6_floating_sphere` | `geometry:source:main_11_floating` | `mechanism:F6:sphere_heave_decay` | `source:official_historical_reuse:main_11_floating` | `parameter:case:o6_floating_sphere` | False | unassigned |
| `W06_narrow_far_partial` | `geometry:derived:w06_rotating_pour:narrow` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_narrow_far_partial` | False | unassigned |
| `W06_narrow_fast_center` | `geometry:derived:w06_rotating_pour:narrow` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_narrow_fast_center` | False | unassigned |
| `W06_narrow_offset_partial` | `geometry:derived:w06_rotating_pour:narrow` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_narrow_offset_partial` | False | unassigned |
| `W06_narrow_slow_center` | `geometry:derived:w06_rotating_pour:narrow` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_narrow_slow_center` | False | unassigned |
| `W06_standard_far_partial` | `geometry:derived:w06_rotating_pour:standard` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_standard_far_partial` | False | unassigned |
| `W06_standard_fast_center` | `geometry:derived:w06_rotating_pour:standard` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_standard_fast_center` | False | unassigned |
| `W06_standard_offset_partial` | `geometry:derived:w06_rotating_pour:standard` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_standard_offset_partial` | False | unassigned |
| `W06_standard_slow_center` | `geometry:derived:w06_rotating_pour:standard` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_standard_slow_center` | False | unassigned |
| `W06_wide_far_partial` | `geometry:derived:w06_rotating_pour:wide` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_wide_far_partial` | False | unassigned |
| `W06_wide_fast_center` | `geometry:derived:w06_rotating_pour:wide` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_wide_fast_center` | False | unassigned |
| `W06_wide_offset_partial` | `geometry:derived:w06_rotating_pour:wide` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_wide_offset_partial` | False | unassigned |
| `W06_wide_slow_center` | `geometry:derived:w06_rotating_pour:wide` | `mechanism:F2:rotating_cup_pour_catch` | `source:derived:w06_rotating_pour_exploration` | `parameter:derived:w06:w06_wide_slow_center` | False | unassigned |

## Control policy

- source and base recipe fields are preserved from the official/custom case definition
- dp, tmax, and tout are explicit batch parameters; missing values remain null
- each case is atomic for trajectory, labels, and split inheritance
- all current split assignments remain null because the D04 production gate is closed
