# F6 physical anchor CPU/native 预检负例（2026-09-21）

这次只执行了一个已经过 root review 的 F6 gravity/entry Definition。授权范围
是一次 GenCase 和一次 native BI4 解码；没有启动 DualSPHysics solver、CUDA/GPU、
queue，也没有写 registry、ledger 或 matrix。全部产物保持
`qualification_claim=none`、`qualification_credit=0`、`T1=false`。

## 执行和验证器记录

GenCase 返回 code 0，生成的粒子分组实际为：fixed `11806`、floating
`693 (mkbound=8)`、fluid `16008`。原始 one-shot verifier 只把
`fixed/moving/fluid` 视为合法标签，漏掉了 GenCase 合法的 `floating` 标签，
因此第一份 receipt 在生成分组门提前失败；它不是 CFD solver 失败，也不能被
当作科学资格证据。

保留原始 receipt 后，按基础设施修复规则完成了一次有界 native-decode amendment。
第一次 amendment 因没有预先创建 `decoded/` 父目录而失败；第二次只消费已经存在
的 XML/BI4 并成功写出 native arrays，但 JSON receipt 序列化遇到 NumPy scalar。
最终 receipt 只读取这批已经解码的数组完成封存，没有再次调用 GenCase 或 decoder。
这些基础设施错误全部保留在 receipt 链中，禁止同输入 GenCase 重跑。

## 硬门结果

native 数组本身通过有限值、唯一粒子 ID、floating/fluid 粒子存在性检查。生成的
floating body metadata 不能满足新 Definition 的连续 body contract：

| 量 | 合同 | GenCase 生成 | 结果 |
|---|---:|---:|---|
| body mass | `2.9952 kg` | `4.32432 kg` | 相对误差 `+44.375%`，失败 |
| COM | `(0.75, 0.30, 0.55) m` | `(0.76, 0.30, 0.56) m` | 最大误差 `0.01 m`，失败 |
| inertia | 连续盒体惯量 | 生成矩阵不同 | 最大相对误差约 `84.8%`，失败 |

因此当前 F6 physical-anchor Definition 在 body mass/COM/inertia 硬门上失败，不能
进入 solver canary，更不能登记为第三个 T1 家族。失败分母保留，credit 仍为零。

## 后续边界

下一步只能建立新的 hash-bound Definition revision，在输入中显式绑定
`massbody`、`center` 和 `inertia`，重新进行 root review 和一次全新的 CPU/native
preflight。不能修改或重跑当前 Definition 来消除这个结果；旧 floating-body
probe 也不能回填 F6 资格。

对应证据：

- 原始 one-shot receipt：
  `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-preflight-v1-20260921/preflight.json`
- 最终 amendment receipt：
  `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-cpu-native-decode-amendment-v2-20260921/amendment-final.json`
- 原始 Definition：
  `campaigns/core-v1/cfd/f6-fluid-rigid-body-physical-anchor-root-review-v1-20260921/CORE_F6_physical_anchor_single_body_gravity_20260921_Def.xml`

