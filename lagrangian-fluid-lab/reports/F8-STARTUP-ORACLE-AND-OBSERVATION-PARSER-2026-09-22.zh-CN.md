# F8 启动瞬态 oracle 与 observation parser（2026-09-22）

本提交补齐两个不需要 CFD 执行授权的静态 blocker：

1. `f8_womersley_oracle_v2.py` 用零初速度的偶对称余弦级数给出启动瞬态，
   显式覆盖 `H²/nu` 黏性扩散尺度，并测试长期趋近稳态 v1 oracle；
2. `f8_observation_parser_v1.py` 实现纯数组 parser 和固定频率的正弦/余弦
   拟合，输出中心速度、壁法向剖面和平均通量的幅值/相位，不允许 time-shift
   拟合或未来参考访问。

两个实现都有独立 contract、SHA-256 和定向测试。它们仍然是 reference/parser
基础设施，不是 CFD 证据；没有写 Definition/control，也没有 GenCase、native
decode、solver、GPU、queue、registry、ledger 或 training。
