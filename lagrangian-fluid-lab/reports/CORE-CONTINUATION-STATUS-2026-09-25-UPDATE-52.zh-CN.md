# UPDATE-52：F8 R008 C-execution 合同 v2 设计复核续作

日期：2026-09-25（Asia/Shanghai）

## 独立只读复核

按用户要求，本次只读审查通过 `gpt-5.6-terra` / `high` 配置请求。回复结论 `REVISE`；回复没有独立模型身份 attestation，所以将其记录为 Terra 配置下的技术意见，不声称模型身份另经认证。未修改实现、测试、冻结输入或权限。

审查指出四项 P0：

1. supervisor attestation 没有 exact schema、受信任密钥来源、认证/撤销和验证路径；executor 自报仍可伪造。
2. TOCTOU 输入闭包未覆盖所有解析后配置、实际读取对象、命名空间和从 hash 前直至全部子进程 reaped 的完整保护期。
3. CPU/GPU source-to-binary 缺少完整 build provenance、工具链/宏/依赖及全部运行期加载代码闭环。
4. C v1 的 `solver_execution` 只有声明字段，C verifier 不读其语义，synthetic `{}` fixture 仍通过；缺少独立 v2 sidecar、digest 绑定、激活规则及禁止 v1 派生 `defined_pass` 的机器约束。

另指出 P1：OPT/argv parser grammar 与覆盖顺序、全控制查询源码调用图、`TERMINATE` exec 前状态/实际 `DirOut` namespace、cgroup 成员连续性/事件丢失；P2：`T_end` 浮点比较来源未冻结、日志解析不能作为单独终止证据。

## 本地源码对照与 v2 草案

- C v1 schema 在 `reports/F8-R008-PER-CASE-PROVENANCE-SCHEMA-V1-2026-09-24.json` 只要求 `solver_execution` 字段存在；`scripts/f8_r008_per_case_bundle_verifier_v1.py` 的 C 分支检查 raw manifest/full axis，未验证该字段。测试 fixture 在 `tests/test_f8_r008_per_case_bundle_verifier_v1.py` 用空 `{}` 仍能闭合结构链。C v1 因此只能继续表示结构层通过。
- 当前 CPU/GPU 调用链的静态 grep 找到 `JSphCpu.cpp` / `JSphGpu.cpp` 向 `AccInput->RunCpu/RunGpu` 传入 `TimeStep`，`JDsAccInput.cpp` 再调用 `GetAccValues(c,timestep)`；这只是直接调用点枚举，尚无绑定 solver build/features 的完整审计调用图。
- `expected_time_axis_hex()` 用 frozen row 中的 cadence 与 endpoint 构建 bit-exact axis。scope 的 `duration_check_atol_s=1e-12` 属于三周期观测窗时长核对，不可借作放宽控制查询域。v2 草案将 CSV endpoint、实际 binary64 query、解析后 `TimeMax/TimeIni/TimeEnd` 作为独立绑定和严格比较对象。
- 新增待审 [合同 v2 草案](F8-R008-C-SOLVER-EXECUTION-EVIDENCE-CONTRACT-V2-DRAFT-2026-09-25.zh-CN.md)：提议 detached C-execution v2 evidence、C v1 compatibility/activation 规则、exact-field bounded payload、JCS+Ed25519 候选签名配置、外置 pinned trust bundle、只读 snapshot/input closure、builder provenance、argv/OPT audit、control call-graph 与严格 horizon、`TERMINATE`/cgroup journals 和 log parser 边界。
- 草案明确当前仓库没有可信 supervisor、受保护签名密钥/信任根、完整事件记录器或 CPU/GPU build attestation。签名算法只能认证字节，不能自证测量可信；没有独立 trust root 时 verifier 必须为 `open`。Rootless `bwrap` 只能提供候选隔离原语，不是该信任根。
- 只读主机能力检查：当前 UID 为 1001；可见 `/usr/bin/bwrap`、`systemd-run`、`keyctl`、OpenSSL，cgroup v2 根列有 `cpu/memory/pids/io` 等控制器；没有可见 `/dev/tpmrm0`。OpenSSL/Python 环境支持 Ed25519，但这只说明有密码学实现，不证明 cgroup 已委派、私钥受保护或存在可信 signer/builder。

## 状态与下一步

当前仍只有静态草案，尚无 C-execution v2 schema 文件、实现或测试；`control_no_extrapolation` 不得判为 pass，R008 `T1_numerical=false`、零资格信用、无 solver/worker/GPU/queue 权限。下一步对 v2 草案做 Terra (`gpt-5.6-terra`, high) 只读 follow-up；只有静态合同审查通过后，才考虑实现一个 fail-closed、仅合成 fixture 的独立 verifier。任何真实 attempt 仍需先解决受信 supervisor/build provenance 与正式执行门。
