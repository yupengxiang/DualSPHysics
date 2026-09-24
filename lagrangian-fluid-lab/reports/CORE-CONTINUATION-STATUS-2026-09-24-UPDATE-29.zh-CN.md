# Core 接续状态 UPDATE-29：F8 R008 逐案例 B/C/D 静态来源闭环

日期：2026-09-24

## 本轮完成

围绕 F8 R008 新增一份逐案例来源 schema、只读 bundle verifier 和 raw BI4 metadata binding API。B/C/D 的 detached manifest 限定精确字段并禁止递归自引用／下游摘要；递归输出树采用 no-follow、稳定身份及单链接检查，目录枚举增量执行并有总条目上限。

D 每帧的 safe-decode receipt 与 metadata manifest 必须以相对路径、字节数和 SHA-256 绑定到封闭的 D outputs manifest。B→C→D 链验证会重新读取 C raw BI4，精确重算 metadata，检查 `TimeStep` binary64 位、重建 XML 与数组字节，并要求每帧 `MassFluid` 位模式等于 B 初始 BI4。MassFluid 保持逐粒固定质量语义；Rhop 单独是动态密度来源。表格文件目前只做路径／大小／摘要闭合，不读 HDF5 数据集。

Terra High（`gpt-5.6-terra`, high）对最终实现给出静态 `PASS`。不可覆盖的源码 review 回执位于 [`per-case-provenance-implementation-review-v1/receipt.json`](../campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008/per-case-provenance-implementation-review-v1/receipt.json)，绑定 decoder、metadata API、verifier 三份源码。校验器要求调用方传入已在外部验证的 review receipt 原始字节；解释器、导入路径和已加载 module 状态仍是调用方 TCB 假设，校验器明确返回“module identity 未独立证明”。

## 验证与权限边界

相关回归共 **62 项通过**：per-case verifier、metadata binding、safe BI4 decoder 及实现 review receipt 合约。另完成 Python 编译、schema JSON 解析和 `git diff --check`。

全部链路数据均为临时合成 BI4；没有读取生产 BI4、生成案例或运行目录，没有调用 GenCase、native decoder、solver、worker、GPU 或队列。`readiness_pass=false`、qualification credit=0；本回执不构成 T1 资格或执行授权。

## 尚未完成

- B 端完整 GenCase XML/几何 cohort、初始原生数组和边界语义审计尚未实现；本轮只重算并绑定初始 BI4 metadata 与必要数组计数。
- D 端 HDF5 dataset 语义、particle ID/cohort 投影、有限值/守恒指标和 T1 adjudication 尚未实现；当前仅验证 table 文件 hash binding。
- 尚无生产 B/C/D 案例 bundle；F8 R008 本轮仍是零信用静态基础设施。
- PLAN 的 Core 全流程仍需推进 CFD 家族资格与生产、至少两个家族的宏观材料资格、正式训练/rollout/评测、可移植打包和异机复现。本轮不代表这些目标完成。

下一步应继续完成 B 侧 cohort 语义及 D 侧 table semantic verifier，再按独立 review 和已批准权限边界逐项推进；不得把本轮合成数据测试当作生产或科学资格证据。
