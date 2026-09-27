# F3 MLP seed17 全 835-step rollout diagnostic

本次只读评测已完成。它使用既有 checkpoint，在 GPU7（`CUDA_VISIBLE_DEVICES=7`，进程内 `cuda:0`）上对 `F3_DEV_00_a0p903125` 的 test split 执行完整 `835/835` transitions；没有重新训练，也没有覆盖既有 `/tmp/f3-mlp500-seed17-20260928-*` 50-step 产物。

结论是：执行链和登记分母完整，但长时域误差爆炸，因此这仍是 non-formal diagnostic，不是资格结果。`formal_eligible=false`、`qualification=false`、`qualification_credit=0`；没有修改源码、manifest、registry、ledger、denominator、gate 或 `PLAN.md`。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`；`data-root=.`；case `F3_DEV_00_a0p903125`；split `test`。
- 模型元数据从 checkpoint 与 training receipt 交叉核对：`mlp`、seed `17`、updates `500`、hidden `8`、centers/update `256`、learning rate `0.001`、normalization transitions `16`、max-neighbors `192`、trainable parameters `534`；全部匹配。
- 评测：`maximum-steps=835`、`chunk-size=34560`、`--diagnostic`、autonomous、`future_state_inputs=false`。
- 新评测产物统一使用 `/tmp/f3-mlp500-seed17-full835-20260928-*` 前缀；checkpoint 只读使用 `/tmp/f3-mlp500-seed17-20260928-checkpoint.pt`。

## 完整登记分母与完整性

- 登记分母：`835 transitions / 836 source frames`。
- requested：`835/835 transitions`，trajectory：`836/836 frames`，`tail_frame_count=0`。
- `failure_category=null`、`first_failure_frame=null`、`requested_window_complete=true`、`finite_rollout_complete=true`。
- raw error coverage：`1.0`；evaluation progress 为 `completed`，`frames_executed=835`，`future_state_inputs=false`。
- HDF5 validator：`passed=true`；trajectory shape 为 position/velocity `[836, 34560, 3]`、valid `[836, 34560]`，position 与 velocity 全部 finite。
- `valid_true_count=28,892,160`、`valid_false_count=0`；mass 为 finite、positive、static，mass total 为 `14.580000378191471 kg`；`validity_mismatch_frames=0`、`changed_particle_mass_frames=0`、`mass_error_abs_max_kg=0.0`。

## 逐 horizon 误差

下面是 audit horizons；原始 evaluation JSON 仍保留全部 `835` 个 per-step 的 position/velocity RMSE 与 ADE 行。单位分别为 m 和 m/s。

| step | position RMSE | position ADE | velocity RMSE | velocity ADE |
|---:|---:|---:|---:|---:|
| 1 | 0.00024638375399337655 | 0.0004084995034183515 | 0.00130784653755144 | 0.0017124540178176757 |
| 10 | 0.002771077314288305 | 0.004170806158246868 | 0.006592829825920217 | 0.01060281558351539 |
| 20 | 0.006162991440813434 | 0.009280816916734397 | 0.0152821124980435 | 0.024651118373957875 |
| 30 | 0.009390783729433841 | 0.014078999140615412 | 0.02766076932978788 | 0.045458798024833394 |
| 40 | 0.01065747783189982 | 0.01592173705328217 | 0.040877606617954365 | 0.06746426946048772 |
| 50 | 0.010632847578936896 | 0.0158230385569207 | 0.052172194024862215 | 0.08457887074159266 |
| 100 | 0.026096951665505585 | 0.03831273627357311 | 0.04160092061349046 | 0.06106575255764818 |
| 200 | 0.07423916907101467 | 0.1080796236875277 | 0.11253684961814862 | 0.1785541269326413 |
| 300 | 0.15617723953594556 | 0.17793233399146438 | 0.323859062625194 | 0.4189357330908872 |
| 400 | 0.5000461180586705 | 0.48890468849849916 | 0.966507163273672 | 0.9954845233359204 |
| 500 | 3.05473487069338 | 2.2398595261523218 | 6.3814827827801475 | 4.696452941335515 |
| 600 | 29.827717057380827 | 19.35121331848832 | 62.27083835423509 | 40.29016622877563 |
| 700 | 258.0128827193025 | 164.03603804608477 | 540.5657809291243 | 343.47860461540455 |
| 750 | 873.1818771126058 | 553.9091481492343 | 1823.7168592330288 | 1156.7976057199885 |
| 800 | 2704.2501769526425 | 1714.2197369614119 | 5661.680377040405 | 3589.021297411091 |
| 825 | 4522.089232314414 | 2866.11044735836 | 9478.208194946033 | 6007.451429673978 |
| 835 | 5584.228376705447 | 3539.145258949665 | 11706.20338058167 | 7419.214424864889 |

末步 position/velocity RMSE 分别为 `5584.228376705447 m` 和 `11706.20338058167 m/s`。执行帧标量 RMSE 为 position `950.4025557349008 m`、velocity `1990.8551559855116 m/s`；selection score 为 `0.5498847081596503`。selection score 仅是登记的 penalty，不是 qualification decision。

## Physics、资源与分析

- physics：`completed_frames=835`；mass error 最大值 `0.0 kg`；validity mismatch `0`；changed mass frames `0`；kinetic-energy error 最大值 `2996945106.656416 J`；wall chord status 为 `checked_static_saved_chords`。
- wall：`1738.2362246059347 s` evaluation wall；GPU 为 NVIDIA RTX 6000 Ada，GPU7 UUID `GPU-88bfe7db-87fb-d458-719b-eb9a098f8f51`；运行期间 `nvidia-smi` 采样显存最大 `607 MiB`，结束后 `18 MiB`。
- RSS：周期性 `ps` 采样最大 `1539896 KiB = 1503.8046875 MiB`；这是采样上界，不冒充进程报告的 allocator peak。
- 观察：状态保持 finite 且 identity/mass/validity contract 通过，但自由 rollout 的误差从短窗水平快速放大；因此不能把 50-step 表现外推成 835-step 质量，也不能据此启动 formal training 或 gate 变更。

按 analyze-results 约定，raw data table 为上表；关键 finding 是“执行完整但长时域不稳定”。任何后续对比都必须继续使用固定 `835` 分母和 `future_state_inputs=false`，并另行获得授权。

## SHA-256

- manifest：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`
- reader manifest：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- case HDF5：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`
- checkpoint：`29aa12d7a7c5293e94e1c3ecd7bca17dd9ba15014846880fb6c2420a0f03ea25`
- training receipt：`33ccfde9185ee9ff53e15f47274bfb12f11058b049ad236f40a68390663b33e9`
- evaluation receipt：`47a57fa1be1d748f35c83e9d996db6353ae94db3534d88f86eb845cf1692d10e`
- evaluation progress：`3a7337d14f07578b8a5b7cc840f7d6b66bf8ed23a2282ba3124ab4a82713a17b`
- trajectory：`ce8f3f9d3a2560fe34ebf2d0c83fff5f9f46f38a33c72688ff5db58d2eeb2853`
- HDF5 validation：`63c4905b8d9b234065bf1e0b8d157d631f0402b6f15e392beaf13e2dbdb3c7d6`
- metric summary：`0389d26a9c8174fa7a60744b5f4988d869d263f24ea34697607805ca1541437a`
- run log：`5d3140dec868f1d45ad59df89958f2411b8467a116a4b3ea0e7120dc7d323bba`

机器可读报告见 [F3-MLP-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json](F3-MLP-SEED17-FULL835-ROLLOUT-DIAGNOSTIC-2026-09-28.json)。
