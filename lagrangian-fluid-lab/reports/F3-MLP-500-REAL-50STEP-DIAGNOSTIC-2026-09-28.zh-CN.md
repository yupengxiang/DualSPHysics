# F3 MLP 500 更新真实 50-step 诊断

本次独立诊断已完成：训练 `500/500` 更新成功，评测在真实案例 `F3_DEV_00_a0p903125` 上按 `maximum-steps=50` 完成 `50/50` 个请求帧。结果仅属于 bounded diagnostic evidence：`future-state=false`、`qualification=false`、`formal_eligible=false`，不产生资格 credit，也不改变任何 gate 或分母。

## 冻结协议

- manifest：`campaigns/core-v1/f3-dataset-v2.json`，`data-root=.`，案例 `F3_DEV_00_a0p903125`。
- 模型：`mlp`，seed `17`，updates `500`，centers/update `256`，hidden `8`，learning rate `0.001`。
- normalization transitions `16`，`max-neighbors=192`，进程设备 `cuda:0`。
- 物理 GPU：`CUDA_VISIBLE_DEVICES=2`，因此进程内 `cuda:0` 对应物理 GPU 2。
- 评测：test split、`chunk-size=34560`、`maximum-steps=50`、`--diagnostic`。
- 所有训练/评测产物均使用唯一前缀 `/tmp/f3-mlp500-seed17-20260928-*`。

## 完成状态与指标

训练 receipt 报告 `evidence_status=complete`、`checkpoint_verified=true`、`completed_updates=500`，参数量 `534`，wall `967.5972436789889 s`。训练最后一个 progress loss MSE 为 `0.08292695134878159`，邻居截断比例为 `0.0`。

评测 progress 报告 `status=completed`、`frames_executed=50`、`execution_complete=true`、`finite_rollout_complete=true`，耗时 `98.29047159990296 s`。固定完整案例分母仍为 `835` transitions / `836` frames；因此 receipt 中的 `failure_category=maximum_steps_limit` 和 `first_failure_frame=51` 只表示 bounded 窗口正常右删失，不是模型执行错误，也没有缩小或改写登记分母。raw error coverage 为 `0.059880239520958084`。

| 指标 | step 1 | step 10 | step 20 | step 30 | step 40 | step 50 |
|---|---:|---:|---:|---:|---:|---:|
| position RMSE (m) | 0.00024638375399337655 | 0.002771077314288305 | 0.006162991440813434 | 0.009390783729433841 | 0.01065747783189982 | 0.010632847578936896 |
| velocity RMSE (m/s) | 0.00130784653755144 | 0.006592829825920217 | 0.0152821124980435 | 0.02766076932978788 | 0.040877606617954365 | 0.052172194024862215 |

selection score 为 `0.9405935132543298`；执行帧平均 position/velocity RMSE 分别为 `0.007008291130781552 m` 和 `0.023878923219391487 m/s`。50-step 末帧 ADE 分别为 `0.0158230385569207 m` 和 `0.08457887074159266 m/s`。trajectory 含初始帧共 `51` 帧、`34560` 粒子，position/velocity 全部 finite，`valid` true 数为 `1762560`；future-state inputs 为 `false`。

## 资源与完整性

训练 receipt 的精确峰值为 GPU allocator `191911936 B`（`183.021484375 MiB`）和 RSS `2858.8515625 MiB`。评测 CLI receipt 不输出进程峰值 RSS，运行期间实时采样到 GPU 2 显存 `607 MiB`、RSS 最大采样 `1191316 KiB`（`1163.39453125 MiB`）；这些是采样值，不冒充进程峰值。训练期间 nvidia-smi 观测到 GPU 2 `687 MiB`，任务结束后的 GPU 2 为 `18 MiB`。

关键输入和源码在运行前后未被写入：manifest、production HDF5、registry、ledger、denominator、gate、`PLAN.md` 均无 mutation。当前基线 commit 为 `bb956fffb6313b2a2c50306826bf1b83d7736a21`；machine JSON 记录了全部输入与运行 artifact SHA-256。

## 结论

这是一条完成的真实 MLP 诊断证据链，不是资格或 formal candidate 结果。`qualification=false`、`formal_eligible=false`、`qualification_credit=0`；不据此启动 full-horizon rollout、formal training 或任何 gate 变更。

machine JSON：[F3-MLP-500-REAL-50STEP-DIAGNOSTIC-2026-09-28.json](F3-MLP-500-REAL-50STEP-DIAGNOSTIC-2026-09-28.json)。

## SHA-256

- manifest 文件：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`
- manifest 声明的 source manifest：`86e27740d764f9769e3255a82a599013a282f1bc4385ad3c29a657a56d9c5bea`
- reader manifest：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- case HDF5 / case record：`8fd78cf3f00fd62b2f0eeaf5092f98f0d2fe235df4d28eaa432f59a609ff06f4`
- known inputs：`089573de6d2c7633b5192bf626fa98eb941f79500f1c1a04b632af68b6ca3bc9`
- control input：`f6852502c7ae5ad7da14faa2dddf3da04e5f02757528e38f3e8c140c00f6389e`
- geometry input：`d7ccdc43108fde81c71f1ef6483258e6b0fa2a3bc9561df063b87a580bc55d70`
- training receipt：`33ccfde9185ee9ff53e15f47274bfb12f11058b049ad236f40a68390663b33e9`
- checkpoint：`29aa12d7a7c5293e94e1c3ecd7bca17dd9ba15014846880fb6c2420a0f03ea25`
- training progress：`96d9c5ed6f313654c6e82f5563b83872fad1a6a9e2ff9949645f918b0dd40936`
- evaluation receipt：`34626600cdf9be57051f22c8b8e8cfcd1e466f0f9f3b61e801ce674afa34a391`
- evaluation progress：`15f539a0f65e11a3bede80326951142c042531842d7f88f4adb598477dc16e2d`
- trajectory：`80ce0dfc4a821d675aa9514ea2cab0381deae09d3f1a17dc7d29810dda1ed039`
- run log：`e9416ea2d8f802d821a44a489dd8b65acef8b5048e620a5120facabd0eb70c8d`
