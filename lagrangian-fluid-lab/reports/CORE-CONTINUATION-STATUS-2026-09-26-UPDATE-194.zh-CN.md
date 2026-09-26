# UPDATE-194：全图与分块 two-hop halo 的 loss/gradient 等价

时间：2026-09-26（Asia/Shanghai）

## 本次推进

PLAN 的图模型验收明确要求全图与 halo 分块不仅预测等价，训练 loss 与梯度也等价。此前已有完整场/分块预测和 commit parity、以及二跳节点能收到梯度的测试，但缺少两条完整反向路径的直接对照。本次在合成六粒子图上新增 raw 与 known-force residual 图模型测试：固定同一组模型参数、完整字段邻居表、目标和非连续 loss centers；将一次全中心前向的抽样 loss/模型参数梯度，与同一 loss centers 按两点分块、使用完整字段 two-hop halo 得到的预测/loss/梯度逐项比较。

新增两种 graph baseline 测试通过；完整 `test_core_models.py` **15 passed**。`py_compile` 与 `git diff --check` 通过。仅 CPU 小型合成图，无 optimizer step、正式训练、solver、GPU、生产数据或资格操作。

## 边界与剩余工作

该回归验证静态 batch 的图网络反向传播等价，不替代 32k optimizer updates、训练 kill/resume、完整全字段规模显存/吞吐实测或正式训练矩阵。Core 仍缺第三个 T1 家族、两个宏观 T2、9 次正式训练及完整 held-out 评测/异机复现。
