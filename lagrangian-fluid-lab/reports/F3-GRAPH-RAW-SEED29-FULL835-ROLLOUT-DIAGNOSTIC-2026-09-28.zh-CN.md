# F3 graph_raw seed29 全 835-step rollout diagnostic

本次只读诊断已完成：使用已核验的 `graph_raw` seed29 checkpoint，在 `CUDA_VISIBLE_DEVICES=5`（进程内 `cuda:0`）上对 `F3_DEV_00_a0p903125` 的 test split 完成完整 `835/835 transitions`、`836/836 frames`。没有重启覆盖末段，也没有重新训练；末段无 scientific/runtime failure。

结论严格限定为完整的 non-formal diagnostic evidence：`diagnostic_only=true`、`formal_eligible=false`、`qualification=false`、`qualification_credit=0`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`。这不是资格结果，不产生 gate、registry、ledger 或 denominator credit。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case `F3_DEV_00_a0p903125`；split `test`。
- 模型：`graph_raw`、seed `29`、update `500`、hidden `8`、trainable parameters `1766`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、max-neighbors `192`。
- rollout：`maximum-steps=835`、`chunk-size=34560`、`--diagnostic`、autonomous、`future_state_inputs=false`；未在本 rollout 中启动训练。
- 运行 GPU：物理 GPU5，`CUDA_VISIBLE_DEVICES=5`，进程设备 `cuda:0`；GPU1/GPU3 上既有外部任务未触碰、未终止任何既有进程。
- checkpoint：`/tmp/f3-graph-raw500-seed29-20260928-checkpoint.pt`，SHA-256 `c675c1915f05a18df3752b2320c076404015e916dc860f76de1e4d20479dabe5`，bytes `100592`。

## 完整分母与 receipt

- full registered denominator：`835 transitions / 836 source frames`。
- evaluation：`frames_executed=835`、`expected_frames=835`、`execution_complete=true`、`finite_rollout_complete=true`、`raw_error_coverage=835/835=1.0`。
- `future_state_inputs=false`；evaluation progress 最终状态为 `completed`，elapsed `15760.240434156032 s`。
- trajectory HDF5 shape：position/velocity `[836, 34560, 3]`，valid `[836, 34560]`，time `[836]`，mass `[34560]`。
- HDF5 validator：`passed=true`、`complete=true`、`trajectory_frames=836`、`trajectory_transitions=835`、`tail_frame_count=0`、`production_artifacts_touched=false`。
- 原始 evaluation 中 `failure_category=null`、`first_failure_frame=null`、`scientific_status=not_assessed`；这是“未作 scientific qualification assessment”，不是末段 runtime failure。

## finite / mass / validity

- position finite：`true`；velocity finite：`true`。
- mass：finite=`true`、positive=`true`、static=`true`；总质量 `14.580000378191471 kg`。
- valid：`valid_true_count=28,892,160`、`valid_false_count=0`，即全部 trajectory validity 为 true。
- physics closure：`mass_error_abs_max_kg=0.0`、`changed_particle_mass_frames=0`、`validity_mismatch_frames=0`。
- 最大 absolute kinetic-energy error：`5.19602272514531 J`；wall chord 检查为 `30833` particles、`13.00767221240676 kg`，语义是 `checked_static_saved_chords`，不是连续路径 qualification。

## selection 与 horizon metrics

selection score 为 `0.16024166138023369`。这是 registered selection penalty（越低越好），不是 qualification decision。原始 evaluation receipt 和 metric summary 保留了全部 `835` 个 per-step position/velocity RMSE/ADE 行。

| step | position RMSE (m) | velocity RMSE (m/s) | position ADE (m) | velocity ADE (m/s) |
|---:|---:|---:|---:|---:|
| 1 | 0.00013167273554621684 | 0.0012660324566573442 | 0.00018734202484334766 | 0.001472431740497897 |
| 10 | 0.0014673441792391433 | 0.0025437760277958656 | 0.0021261818519883228 | 0.003356680979769968 |
| 20 | 0.0035649070125166075 | 0.003948135082537215 | 0.0051963431369563655 | 0.005945462868739797 |
| 30 | 0.005695038178226528 | 0.007620330373120689 | 0.008220084299604729 | 0.011670619375264975 |
| 40 | 0.006398257962484392 | 0.019190777218135894 | 0.008948917897667467 | 0.03004629785160193 |
| 50 | 0.006190025948475731 | 0.035656176158284106 | 0.008657046060485306 | 0.054067072515159825 |
| 100 | 0.024121084993890526 | 0.03042605009056382 | 0.034606551906402175 | 0.04734911035009475 |
| 200 | 0.09505671595996464 | 0.05411856357876375 | 0.15080925638514942 | 0.08041670177503282 |
| 300 | 0.08479526904719546 | 0.16576382001643297 | 0.1277501121699064 | 0.25762319532378025 |
| 400 | 0.17307299073651303 | 0.16971007929046253 | 0.2825319223659018 | 0.2460327075096606 |
| 500 | 0.24856269294799185 | 0.2386275832031628 | 0.4131402985349554 | 0.3778460157256754 |
| 600 | 0.2989597606727129 | 0.19858423944267406 | 0.47442431009571107 | 0.26815301739749053 |
| 700 | 0.47617387257664645 | 0.29304236729019095 | 0.7558116515943916 | 0.38293764791711554 |
| 750 | 0.5309400133604188 | 0.4214366234105074 | 0.7957074508444782 | 0.551621678558163 |
| 800 | 0.6308160951709387 | 0.44249281785499384 | 0.9215097884020175 | 0.6090633685955721 |
| 825 | 0.7025823650036847 | 0.507257338874806 | 1.0330345534346386 | 0.7125220225482216 |
| 835 | 0.7333479798959484 | 0.5210208544455348 | 1.0797484886167694 | 0.7086194620634868 |

用户要求的关键 horizon 指标为：

- step 50：position RMSE `0.006190025948475731 m`；velocity RMSE `0.035656176158284106 m/s`。
- step 835：position RMSE `0.7333479798959484 m`；velocity RMSE `0.5210208544455348 m/s`。
- 全执行帧 scalar：position RMSE `0.30112407557172416 m`；velocity RMSE `0.2290529514856505 m/s`。

## qualification / formal 判定与诊断性质

本次没有 qualification 或 formal claim：`qualification=false`、`formal_eligible=false`、`qualification_credit=0`、`T1_numerical=false`、`T2_macro=false`、`T2_path=false`。完整 rollout、finite、mass 和 validity 通过，只能说明执行链与数值/数据闭合 receipt 完整；它不能把 diagnostic 自动升级为 formal acceptance、T1 或 T2。长时域误差从 step 50 到 step 835 明显增大，因此该结果应作为只读诊断证据使用，不应外推为 qualification 性能。

本次未修改源码、生产 HDF5、manifest、registry、ledger、denominator、gate 或 `PLAN.md`；没有启动 solver/worker/training，没有覆盖既有 50-step 产物，也没有终止其他进程。

## receipts SHA-256

- training receipt：`6ff3e753baf3163cfabe1cde49e0c8e06182b5aa861f45b2ec289f5a1bdfc2da`
- training progress：`7f77360e51c022214027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- evaluation receipt：`33bf2369fa24f9ae764384f9d9dab0fd84b6ea84c99120a0b9d8fe8e487a975a`
- evaluation progress：`6c7f75669305554e525bc4d3d516740f67befbf05f3a270295089d4204830048`
- trajectory HDF5：`510d1f4cb7ec38b591e71e58e40b8e973a0f5d1bd2a7c064a69b496fb64b95bb`
- HDF5 validation：`2690c254a807508983fef3ad2efb056634cc728ce0c1dc26d87c93a321a11c63`
- metric summary：`cf4b11158d85b47d0f41725b36cbf53ba25f83d5a3bcd84670f379fcc9226118`
- run log：`09e6bf2cc59ba15ab9cb073b728a6aaea38d6bae76f5d01e5ec8fc84a9d0beb2`

机器可读报告见 `F3-GRAPH-RAW-SEED29-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json`。
