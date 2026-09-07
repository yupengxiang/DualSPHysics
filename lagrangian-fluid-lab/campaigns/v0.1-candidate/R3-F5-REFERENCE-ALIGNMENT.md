# R3 F5 CIEMito 外部波高计对齐探针

状态：**candidate-only；不授权正式数据发布**。

该探针将模型四条垂向 SWL 线与官方 CIEMito 表中的四列波高计观测进行对齐诊断。模型每条曲线先减去自身首个 SWL 值；参考表的原始重复时间戳被保留并按相同时间的算术平均用于插值。

结果仅回答“当前输出链能否形成可复查的时间序列比较”，不回答“数值模型已经通过外部物理验证”。

- coarse (dp=0.03 m): fixed t=0 mean RMSE 15.52 mm; local ±0.5 s diagnostic 15.50 mm at offset -0.008 s.
- medium (dp=0.025 m): fixed t=0 mean RMSE 10.90 mm; local ±0.5 s diagnostic 10.89 mm at offset -0.004 s.
- fine (dp=0.02 m): fixed t=0 mean RMSE 8.87 mm; local ±0.5 s diagnostic 7.26 mm at offset +0.054 s.

仍未验证坐标/高程基准等价性、测量不确定度和预注册的事件指标；局部时移只是相位敏感性诊断，不能作为物理校准。机器可读详情见 `r3-f5-reference-alignment.json`。
