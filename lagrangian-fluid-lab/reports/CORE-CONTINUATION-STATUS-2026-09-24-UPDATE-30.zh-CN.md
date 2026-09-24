# Core 接续状态 UPDATE-30：F8 R008 B/C 粒子身份闭环

日期：2026-09-24

## 本轮实现

在 UPDATE-29 的 F8 R008 逐案例 B/C/D 静态 bundle verifier 上，补入一段仅处理粒子身份的 B→C 语义检查：对有界、稳定读取的 GenCase XML 做 event-wise 解析，拒绝 DTD/entity、超出 16 MiB／深度 256／250000 元素限额、未知组、非规范 begin/count、uint32 越界、重叠或缺口；重算 fluid/fixed/moving/floating 的 ID 区间及计数，并与初始 BI4 的 `CaseN*` 元数据核对。B 初始 BI4 和每个 C raw BI4 帧的 `Idp` 均须是完整、无重复的 `[0, CaseNp)` little-endian uint32 身份全集。

B receipt 的 `particle_cohorts` 现在必须逐字段等于从已绑定 XML 与 BI4 重新计算的 cohort 记录；C 每帧还须保持 B 的群组计数及完整 ID 集。schema 和 synthetic tests 同步更新。旧 v1 Terra High receipt 保留不改；verifier 的 caller-trusted review 合约升至 v2，并以 [`per-case-provenance-implementation-review-v2/receipt.json`](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v2/receipt.json) 独立封存最终复审。

## 当前验证与边界

Terra High 首轮 v2 复审给出 `REVISE`，指出成功路径/资源边界/C 帧分类计数测试不足；已补入多段四组 cohort 成功例、16 MiB/深度/元素上限、UTF-16 DTD 回调及 C `CaseN*` 分类漂移链级负例，并经 Terra High high-effort 再审 `PASS`。新的不可覆盖 v2 receipt 绑定 decoder、metadata API、verifier 三份当前源码。相关五个测试模块共 **77 项通过**（per-case verifier、metadata API、safe BI4 decoder、历史 v1 receipt、当前 v2 receipt）；Python 编译、schema JSON 解析和 `git diff --check` 通过。

没有读取或修改生产案例 bundle；没有调用 GenCase、native decoder、solver、worker、GPU 或队列。全流程仍 `readiness_pass=false`、qualification credit=0。本轮尚未审计 Definition/control 的完整 frozen-input 语义、几何/边界/法向、HDF5 dataset 内容、守恒指标或 T1 adjudication。

## 下一步

接下来继续 D table 的独立版本化语义验证：完整时间轴、fluid ID 投影、位置/速度/密度/质量数据集与上游来源重算；再补 Definition/control 与几何/边界/法向审计。不能把当前的 hash-only table binding 或 synthetic fixture 当作生产或科学资格证据。
