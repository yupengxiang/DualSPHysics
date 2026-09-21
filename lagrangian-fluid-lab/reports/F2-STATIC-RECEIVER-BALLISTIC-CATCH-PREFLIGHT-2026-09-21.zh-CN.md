# F2 静态接收盆自由落体捕获：root review 与 CPU/native 预检（2026-09-21）

这次执行把全新的 F2 `stationary_receiver_ballistic_slug_capture` 候选从 proposal 推进到一次输入级预检。它仍然不是 T1 资格研究：预检只检查 literal Definition、GenCase 初始粒子和 native 身份／有限性／质量／初始几何硬门，事件窗口、solver 动力学、材料和 15 行矩阵都没有执行。

## 授权边界

root-review receipt [root-review-receipt-v1.json](../campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/root-review-receipt-v1.json) 的状态为 `authorized_one_fresh_cpu_native_preflight_only`。它绑定 proposal、literal Definition writer 和全新 case/output namespace，只允许一次 GenCase 与一次 native decode；solver、GPU、job、queue、ledger、registry 和 matrix submission 全部关闭。旧 F2 的 Definition、generated XML/BI4、trajectory 和 output stem 没有进入这条输入谱系。

随后由 writer 生成 [Definition](../campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/input/CORE_F2_STATIC_RECEIVER_BALLISTIC_CATCH_q0p50000000_dp0p007500000000_anchor_Def.xml) 与 definition contract。几何为固定外槽、固定开口接液盆和其上方的有限液块；`q=0.5` 只决定接液盆的静止 y 位置，源液块以 `[0,0,-0.2] m/s` 的初速度下落。源格点为 `32×24×24=18,432` 个粒子，质量使用原生 `rho*dp^3`，没有重标定。

## 预检结果

预检 receipt [preflight.json](../campaigns/core-v1/cfd/f2-static-receiver-ballistic-catch-v1/preflight/preflight.json) 的状态为 `cpu_native_preflight_pass`，但 `qualified=false`、`qualification_claim=none`、`matrix_credit=0`。GenCase 返回码为 0，生成的初始 native frame 为：

| 项目 | 结果 |
|---|---:|
| 总粒子 | 118,509 |
| 边界粒子 | 100,077 |
| 流体粒子 | 18,432 |
| native 粒子质量 | 0.000421875 kg |
| 连续源质量 | 7.776 kg |
| 相对质量误差 | `2.22e-16` |
| ID 唯一且与 generated XML 对齐 | 通过 |
| 位置、速度、密度有限 | 通过 |
| 外槽闭合面外的初始流体端点 | 0 |
| 接液盆闭合面重叠的初始流体端点 | 0 |

初始硬门通过只说明输入可被可靠物化和读取；它没有证明长时域动力学稳定、接液事件完整、质量留存／溢出结果可重复，也没有授权 solver anchor。15 行父分母仍保持 `executed=0`、`credit=0`，并且禁止对同一输入重试。

## 验证与下一步

定义 writer、root-review、preflight 的静态检查及其回归共 **8 passed**；另有 proposal validator **5 passed**。`verify-preflight` 仅读取 receipt 与产物哈希，返回 `status=ok`。所有执行控制字段都保留 solver/GPU/queue/ledger/registry/matrix 为关闭或零。

下一步若继续推进，只能先对这份初始硬门证据进行独立 root 审阅，再决定是否为全新 solver anchor 写受保护 job spec。即使 solver anchor 成功，也必须完成完整事件窗、15 行资格矩阵和逐例审计后才能讨论 F2 T1；当前 Core gate 不变。
