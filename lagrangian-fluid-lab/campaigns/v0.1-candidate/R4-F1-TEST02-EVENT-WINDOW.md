# R4 F1 Test 02 event-window follow-up

状态：**仅诊断，不是物理验收或 Gold 标签。**

本实验复用官方 SPHERIC Test 02 DualSPHysics mDBC 背景，保留 W05 的三档空间分辨率，
将时域截取为 `0--2.2 s`，请求输出间隔为 `0.005 s`。它只回答输出频率是否足以解析压力冲击。

| level | dp (m) | GPU | status | frames | median cadence (s) |
|---|---:|---:|---|---:|---:|
| coarse | 0.040 | 4 | completed | 440 | 0.004999999999999893 |
| medium | 0.030 | 5 | completed | 440 | 0.0049970000000000014 |
| fine | 0.020 | 6 | completed | 440 | 0.0050000000000001155 |

## 解释边界

- 不能用本轮首个冲击窗口替代 W05 的完整 6 秒 Test 02 验证。
- 峰值定义为带符号压力的最大绝对值极值；正压冲量单独报告，不能把负压伪峰当作正向冲击。
- 必须逐探针报告峰值、峰时、误差和正压冲量；不能用单一 RMSE 排名。
- 只有在事件窗口、宏观水位、质量/穿透以及三分辨率趋势共同过 gate 后，F1 才能进入 pilot 候选。

机器可读结果：`campaigns/v0.1-candidate/r4-f1-test02-event-window.json`。
