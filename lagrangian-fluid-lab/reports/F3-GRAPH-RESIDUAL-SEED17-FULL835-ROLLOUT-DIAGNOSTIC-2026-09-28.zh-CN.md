# F3 graph-residual seed17 full835 rollout diagnostic

日期：2026-09-28。该报告记录一次只读、非正式的 F3 全时域 rollout diagnostic；不构成 release、qualification 或 gate 证据。

## 结论

- rollout 成功完成：835/835 transitions，HDF5 为 836/836 frames；failure_category=null，finite_rollout_complete=true。
- HDF5 validator：passed=true、complete=true、fail_closed=false、production_artifacts_touched=false。
- future_state_inputs=false；raw_error_coverage=1.0（835/835）。
- 明确非正式：formal_eligible=false、qualification=false、credit=0。该结果不修改 denominator、gate、registry、ledger 或 PLAN。

## 协议与来源

- manifest：campaigns/core-v1/f3-dataset-v2.json；SHA256 8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680；data-root .；case F3_DEV_00_a0p903125；split test。
- 模型：graph_residual，seed 17，updates 500，hidden 8，max_neighbors 192。
- 评测：maximum_steps=835，chunk_size=34560，diagnostic=true，future_state_inputs=false，设备 CUDA_VISIBLE_DEVICES=7 / 进程内 cuda:0。
- checkpoint：/tmp/f3-graph-residual500-seed17-20260928-checkpoint.pt，bytes 101421，SHA256 1f64ebd53eb794d87562a87c43a37db4ac8b8f7e2f3b1cc994a6a7baf448eb96；仅读取，未训练。
- case source：campaigns/l1-resume/data/continuation/F3_DEV_00_a0p903125.h5，bytes 899562494，SHA256 8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4。

## 完整性与 HDF5

- trajectory shape：position [836, 34560, 3]，velocity [836, 34560, 3]，valid [836, 34560]，time [836]。
- transitions/frames：835/836；particles 34560；time 0 → 8.35001282822348 s。
- finite：position True，velocity True，mass True，time True；valid 全部为 true True，false count 0。
- mass：sum 14.5800003781915 kg，min/max 0.00042187501094304/0.00042187501094304 kg；unique particle IDs 34560。
- HDF5 attrs：future_state_inputs=False，autonomous_prediction=True，state schema core.state.native_velocity.v1。

## 逐 horizon position/velocity 指标

机器 JSON 中保存了全部 835 个 horizon 的四个 raw 指标；下表列出关键 horizon 和末步。单位：position 为 m，velocity 为 m/s。

| horizon | position ADE | position RMSE | velocity ADE | velocity RMSE |
|---:|---:|---:|---:|---:|
| 1 | 1.27793726278012e-05 | 9.21844748532368e-06 | 0.00207956623676486 | 0.00155926384561574 |
| 10 | 0.000468844674117262 | 0.000340467124528529 | 0.00982941307445431 | 0.00683256078758369 |
| 20 | 0.00196498741903991 | 0.00138544723272764 | 0.0231492343393555 | 0.0156688309890246 |
| 30 | 0.00495374410088213 | 0.00340413061428864 | 0.0387861882733709 | 0.0255577014665608 |
| 40 | 0.00954377225655743 | 0.00636649366197747 | 0.0563482780172616 | 0.0361552058488926 |
| 50 | 0.0161201606436212 | 0.0104262182301563 | 0.0838189386584794 | 0.0529934419010521 |
| 100 | 0.114867339637786 | 0.0690876602192319 | 0.345881626347845 | 0.201312464312988 |
| 200 | 0.382007813336781 | 0.223139203978328 | 0.151738154429874 | 0.107878324949768 |
| 300 | 0.608546792282714 | 0.368369953657173 | 0.531976095112647 | 0.359498156960428 |
| 400 | 1.08151864759699 | 0.76260418980196 | 0.956110225121672 | 0.807175745736694 |
| 500 | 2.26717917533291 | 1.76608643089053 | 1.70641914131691 | 1.4147060071501 |
| 600 | 4.65378765542696 | 3.70559918181874 | 4.01401259670455 | 3.22039112890541 |
| 700 | 10.2849682306998 | 8.06512025004817 | 8.73246401837821 | 8.29008042759793 |
| 800 | 22.6316702160942 | 22.3976461973642 | 21.9818023693537 | 35.5793386833948 |
| 835 | 29.9133147566807 | 36.1630526931276 | 31.4580473554262 | 62.0547210240679 |

- 全时域聚合：position ADE 4.61751017203612 m，FDE 29.9133147566807 m，RMSE 8.03790996106956 m；velocity ADE 4.29110212946323 m/s，FDE 31.4580473554262 m/s，RMSE 12.3947562768304 m/s。
- raw frame mean：position RMSE 4.08546468505052 m；velocity RMSE 5.42041134580005 m/s；selection score 0.552571879038831（仅 diagnostic）。
- 末帧预测场均值：position ['10.7054872512817', '-5.23068332672119', '-21.3770637512207'] m；velocity ['18.7114963531494', '-8.56831932067871', '-6.18212938308716'] m/s。初帧均值 position ['-1.21244403405996e-09', '6.46751792746092e-12', '0.0449984706938267'] m、velocity ['0', '0', '0'] m/s。

## selection / physics

- physics 覆盖 835/835 frames，全部 finite True。
- mass error abs max 0 kg；validity mismatch frames 0；changed-particle-mass frames 0。
- kinetic-energy error abs max 84240.2244885678 J；wall-chord 累计 particle count 36676、mass 15.4726879013469 kg；status ['checked_static_saved_chords']。

| horizon | mass error kg | kinetic-energy error J | validity mismatch | changed mass | wall-chord particles | wall-chord mass kg |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | -2.35506170826924e-05 | 0 | 0 | 0 | 0 |
| 10 | 0 | 0.00094392903275419 | 0 | 0 | 0 | 0 |
| 20 | 0 | 0.00520849162082137 | 0 | 0 | 0 | 0 |
| 30 | 0 | 0.014313044033681 | 0 | 0 | 20 | 0.00843750021886081 |
| 40 | 0 | 0.034727951901933 | 0 | 0 | 43 | 0.0181406254705507 |
| 50 | 0 | 0.0909766941864065 | 0 | 0 | 9 | 0.00379687509848736 |
| 100 | 0 | 0.952590581565302 | 0 | 0 | 200 | 0.0843750021886081 |
| 200 | 0 | 0.178382287161457 | 0 | 0 | 128 | 0.0540000014007092 |
| 300 | 0 | 1.70192857740207 | 0 | 0 | 38 | 0.0160312504158355 |
| 400 | 0 | 13.3709216942555 | 0 | 0 | 55 | 0.0232031256018672 |
| 500 | 0 | 41.5396771971795 | 0 | 0 | 0 | 0 |
| 600 | 0 | 225.344235789736 | 0 | 0 | 0 | 0 |
| 700 | 0 | 1503.21947764002 | 0 | 0 | 0 | 0 |
| 800 | 0 | 27716.0683145804 | 0 | 0 | 0 | 0 |
| 835 | 0 | 84240.2244885678 | 0 | 0 | 0 | 0 |

物理检查采用 saved-chord/static-wall diagnostic 语义；不作 exact continuous-path 或 formal qualification 声明。

## GPU、RSS、wall

- GPU：物理 GPU 7（RTX 6000 Ada），CUDA_VISIBLE_DEVICES=7，进程内 cuda:0；外部 nvidia-smi 采样峰值 3049 MiB。
- RSS：VmHWM=3558176 kB = 3474.78125 MiB。
- rollout wall：8635.58931087912 s，取自 core.rollout.progress.v1 elapsed_seconds；progress 最终状态 completed，completed_frames=835。

## 产物 SHA256

| 产物 | bytes | SHA256 |
|---|---:|---|
| /tmp/f3-graph-residual500-seed17-full835-20260928-evaluation.json | 6391035 | e1c18b483a763a57f5491823ee4a972103a1eff7fbdaa145603468a070a1b9d6 |
| /tmp/f3-graph-residual500-seed17-full835-20260928-evaluation-progress.json | 654 | 82a249bd42eac766687e0f38514a8b0b88dfc228b4b7b6050904dc3e9dbc074f |
| /tmp/f3-graph-residual500-seed17-full835-20260928-trajectory.h5 | 723148320 | 0b8bf5ca42776513ece90c816f6651f45149eb0a22bd98085c2544f11d9152e3 |
| /tmp/f3-graph-residual500-seed17-full835-20260928-evaluate.log | 2101 | 69ea3d27292de4dd8d4e51d728d5d50913a3db3d7599ae07f739a92734785c48 |
| /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/f3-dataset-v2.json | 93710 | 8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680 |
| /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/core_learning.py | 144749 | 3eefe1441dabb350182090c3625f24a8209543a4a31d02521f283074c996c27b |
| /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/core_models.py | 48054 | 20e635ebd25cd511eeff6f84478678d3364608fd86a5d4b67e2aa53a0d88295d |
| /home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/scripts/f3_full_rollout_receipt_hdf5_validator_v1.py | 24628 | 7ae20056d0f0c610af86714730e170edba9b1e36f50e38dcf47f0afbd61cdec1 |
| /tmp/f3-graph-residual500-seed17-20260928-checkpoint.pt | 101421 | 1f64ebd53eb794d87562a87c43a37db4ac8b8f7e2f3b1cc994a6a7baf448eb96 |

## 变更边界

- 只新增本报告对应的机器 JSON 与本中文报告；只 stage/commit 这两个报告文件。
- 源码、manifest、registry、ledger、denominator、gate、PLAN.md、生产 HDF5 均未修改；已有 residual 50-step 产物未覆盖。
- 该 full835 receipt 已完成但仍 fail-closed 于正式资格：formal_eligible=false、qualification=false、qualification_credit=0、credit=0。

机器明细：reports/F3-GRAPH-RESIDUAL-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json。
