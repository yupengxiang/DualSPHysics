# F2 H2 mDBC static-range 离散化修复审计（2026-09-21）

现有 v4 H2 static-range 15-cell CPU/native 预检为 14/15 通过；固定 held-out cell 11（q=0.75，dp=0.0075）因第三源层相对质量误差 `0.02806106870228997 > 0.025` 失败。该失败保留在原始 15 行分母中，没有重跑同一输入，也没有删除失败行。

本次只采用一类有证据的修复假设：`H2_v5_top_layer_lateral_lattice_balance`。它保持两个较低源层和连续几何不变，只对第三源层选择居中的整数横向格点计数；cell 11 由旧 `[43,29,16]` 调整为新 `[42,29,16]`，第三层误差由 `0.02806106870228997` 降至实测 `0.004152671755724757`，总离散质量误差为 `0.0036100658513640305`。质量门仍固定为 source `0.025`、total `0.03`，不进入优化，也不做质量重标定。

已有 v5 full-scope CPU/native 证据显示 15/15 行通过，cell 11 的 normal/identity/finite/mass checks 均通过；这只是输入闭合，资格 credit 仍为 0，solver product 不存在。由于单一假设已在 full scope 预检中通过，本合同不增加第二个未经验证的修复类别。

## 固定边界

- 保留失败：v4 `prepared=14`、`failed=1`；cell 11 source errors=[0.0033276382708198327, 0.0033276382708198327, 0.02806106870228997]。
- 新输入：v5 output stem `/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/core-v1/cfd/f2-h2-mdbc-static-range-qualification-v5/prepared-20260920-v5-all`，15/15 CPU/native pass，`qualification_credit=0`。
- native mass policy 为 `rho*dp^3`，不允许质量重标定；未知/失败行仍保留，不能 survivor renormalization。
- 本轮脚本只读取和绑定既有证据，不运行 GenCase/decoder，不启动 solver/GPU/queue，不写 ledger/registry。

## 资格边界和下一步

v5 仍是 qualification-only CPU/native closure，不能替代静态事件、runtime hard-integrity 或 15-cell T1 evaluator。下一步只能由独立 root review 审查该闭合后再决定是否生成新的 runtime proposal；本合同不授权任何 runtime。

## 产物

- contract：`campaigns/core-v1/cfd/f2-h2-mdbc-static-range-repair-preflight-contract-20260921.json`。
- implementation：`scripts/f2_h2_mdbc_static_range_v5_prepare.py`，SHA `9bcf81d456b16805259055ce00cb0a78084afac65d8ab93e2cbc2ab3c6e6c2ef`。
- contract 的 `hash_bindings` 固定绑定 v4 failed matrix/cell、v5 candidate/plan/full matrix/cell 11 preflight/prepared、materializer 和回归测试。

Core gate 未改变：third T1 family 未建立，qualification credit=0，registry/ledger mutation=0。
