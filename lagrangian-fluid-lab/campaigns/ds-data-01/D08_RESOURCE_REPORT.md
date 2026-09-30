# DS-DATA-01 resource report

This is an observed resource/provenance report for dataset construction. It contains no training or model qualification accounting.

## Official package

- Root: `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4`
- Version: `DualSPHysics5             v5.4.355            08-04-2025`
- Files: 2435; example groups: 14; PDFs: 16.

## D05 resource totals

- Planned cases: 8; Solver replays: 7; reference reuse: 1.
- Sum of Solver wall times: 1701.2 s.
- Raw Solver output: 4.05 GiB; PartVTK CSV: 18.18 GiB; normalized HDF5: 2.75 GiB.
- GPU assignments: B05_F1_main_dambreak3d_dp030=GPU1, B05_F1_mdbc_dambreak3d_dp030=GPU2, B05_F3_sloshing_motion_dp030=GPU3, B05_F4_shapes_inlet3d_dp030=GPU4, B05_F5_solitary_wave_kdv_dp030=GPU5, B05_F6_floating_box_dp030=GPU6, B05_F7_pump3d_dp030=GPU7.

## Final snapshot

- Filesystem free at report time: 7.61 TiB of 14.44 TiB.
- Process classifications: {'preexisting_dataset_activity': 4, 'unresolved_user_process_observe_only': 1}.
- GPU policy: GPU0 remained protected; D05 used only fresh-preflight idle GPUs in the internal pool; all GPUs were idle after completion.
- Unrelated pre-existing processes were observed only and were not stopped.

## Evidence boundary

- Large raw/CSV/HDF5 payloads remain local and are referenced by compact receipts and hashes.
- CPU/disk conversion did not require a GPU.
- No learning, inference, checkpoint replay, ranking, or model qualification was started.
