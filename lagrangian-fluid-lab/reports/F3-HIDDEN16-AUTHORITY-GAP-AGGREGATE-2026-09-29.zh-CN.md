# F3 hidden16 authority-gap aggregate

这是九个 F3 hidden16 model×seed authority-gap JSON 的只读聚合验证结果。它只验证覆盖、fail-closed、zero-credit 与 launch denial，不授予 formal/T1/T2、training、scheduler authority 或 Core gate。

- status：`blocked_fail_closed`；fail-closed：`True`
- coverage：`9/9`，complete unique=`True`
- aggregate credit：`0`；launch_allowed=`False`；Popen=`False`
- 输入读取：仅九个显式 gap JSON，有界 strict JSON、拒绝 symlink、要求单 hardlink；未读取 production manifest/checkpoint/trajectory/HDF5、scheduler/root authority 或 GPU。

| model | seed | input status | authority verified | zero credit | launch denied |
|---|---:|---|---:|---:|---:|
| `graph_raw` | `17` | `blocked_projection_gap` | `False` | `0` | `True` |
| `graph_raw` | `29` | `blocked_projection_gap` | `False` | `0` | `True` |
| `graph_raw` | `43` | `blocked_fail_closed` | `False` | `0` | `True` |
| `graph_residual` | `17` | `blocked_projection_gap` | `False` | `0` | `True` |
| `graph_residual` | `29` | `blocked_projection_gap` | `False` | `0` | `True` |
| `graph_residual` | `43` | `blocked_projection_gap` | `False` | `0` | `True` |
| `mlp` | `17` | `blocked_projection_gap` | `False` | `0` | `True` |
| `mlp` | `29` | `blocked_projection_gap` | `False` | `0` | `True` |
| `mlp` | `43` | `blocked_fail_closed` | `False` | `0` | `True` |

所有九条入口仍缺真实 external scheduler authority、trusted root/key 或完整 authority-bound terminal evidence；本聚合不把 caller claim 变成可信 authority。
