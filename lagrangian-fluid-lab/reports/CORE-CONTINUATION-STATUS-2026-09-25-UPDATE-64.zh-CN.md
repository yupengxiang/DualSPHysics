# UPDATE-64：收敛 F8 R008 synthetic harness v5 草案边界

对 v5 草案继续做只读设计核对，补充 lexical depth scanner 对未配对右括号、字符串转义和 EOF 的确定行为，使 malformed JSON 的 `too_deep`/`bad_json` 优先级可以按同一状态机复现。

按用户要求发起 `gpt-5.6-terra` / `high` 子代理审查请求；该 agent 未审阅草案，并回复当前无法提供 Terra High 子代理/委派接口，亦未提供可验证身份或 effort attestation。因此本轮不计为 Terra High review，也不记录普通技术 PASS/REVISE。v5 仍为待审草案。

未实现 parser、未增加或运行测试、未盘点/改接生产 consumer，未读取 production evidence；未启动 GenCase/native decoder/solver/worker/GPU/queue。R008 execution gate 仍为 `open`、`T1_numerical=false`、资格信用为零。实现前仍须有有效 Terra High 静态设计审查、现存生产消费者盘点及拒绝测试合同；此草案及其诊断不得进入生产资格入口。
