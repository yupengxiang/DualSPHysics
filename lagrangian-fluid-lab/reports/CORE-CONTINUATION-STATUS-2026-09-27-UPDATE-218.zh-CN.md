# UPDATE-218：F4 v5 候选实现只读复核

时间：2026-09-27（Asia/Shanghai）

Terra High（配置：`gpt-5.6-terra`, high；agent `01a0de6c-189b-7ee1-b6bc-7c61828fdfca`）只读检查 F4 v5 blend 实现、测试、v3/v4 依赖及 UPDATE-216 screen receipt。未发现 P0/P1；复核确认 blend 公式准确、沿用 v4 support/gate，v3/v4 不一致时 fail closed，analytic screen 仅支持准备受限 preflight，不支持 superiority 或 qualification。reviewer 未执行测试、评分、HDF5 读取或运行任务，且无法 attestate 模型身份。

保留一项 P3 维护建议：v5 依赖 v3/v4 对无效 velocity/query/walls 作 fail-closed；当前 v5 定向测试直接覆盖的非有限输入只有 position。此项没有证据表明当前行为错误；为不改变已哈希绑定的候选代码/测试及既有评分回执，本轮不改候选实现或测试。后续 candidate-specific preflight 只验证静态闭包、资源和源 HDF5 元数据，不执行 v5 predictor，也不构成运行许可。
