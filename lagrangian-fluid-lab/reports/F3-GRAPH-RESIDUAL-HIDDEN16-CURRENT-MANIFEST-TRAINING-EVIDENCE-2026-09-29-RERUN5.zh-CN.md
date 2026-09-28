# F3 graph_residual hidden16 current-manifest training evidence

- 状态：`diagnostic_bound`；source-bound=`True`；fail-closed=`False`
- model/config：`graph_residual` / hidden `16` / updates `500` / seeds `17,29,43`
- 权限边界：diagnostic-only；formal/T1/T2/qualification=false；credit=0；未启动或控制 GPU
- canonical manifest SHA：`5d53fd9c1bfed991027f23464d9d11f533bf7d766c960aab6986e91c83f4c768`
- raw manifest SHA：`8d87da6a4aaf3013461a757815b5eb95c1d46311dcb0657537479b573076e680`
- bounded receipt JSON opened：`3/3`；checkpoint/HDF5/trajectory/progress 未打开

## Training receipts

| seed | status | run_id | receipt | checkpoint |
|---:|---|---|---|---|
| 17 | `bound` | `f3-graph_residual500-hidden16-currentmanifest-seed17-20260929-v3` | `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed17-20260929-v3-training.json` | `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed17-20260929-v3-checkpoint.pt` |
| 29 | `bound` | `f3-graph_residual500-hidden16-currentmanifest-seed29-20260929-v3` | `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed29-20260929-v3-training.json` | `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed29-20260929-v3-checkpoint.pt` |
| 43 | `bound` | `f3-graph_residual500-hidden16-currentmanifest-seed43-20260929-v3` | `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed43-20260929-v3-training.json` | `/tmp/f3-graph_residual500-hidden16-currentmanifest-seed43-20260929-v3-checkpoint.pt` |

## 边界

本 intake 只消费 bounded manifest/receipt JSON 元数据，并复用现有 graph_residual current-manifest matrix 的 residual evidence validator；不读取 checkpoint 内容，不读取 HDF5、trajectory、evaluation、progress，不规划或启动 rollout。正向绑定也不产生 Core formal、T1/T2、qualification、denominator、registry、ledger、gate 或 completion credit。
