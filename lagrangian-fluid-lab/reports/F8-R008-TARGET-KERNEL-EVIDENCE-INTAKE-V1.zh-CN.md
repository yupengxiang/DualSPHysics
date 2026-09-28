# F8/R008 target-kernel evidence intake contract V1

## 当前结论

- 状态：`blocked_missing_external_target_evidence`
- 外部 manifest：`external/f8-r008-target-kernel-evidence-manifest-v1.json`，当前仓库中不存在
- kernel release/source commit/source tree/UAPI/build-id/config/required options：均未宣称为 target pin
- source/UAPI/config/build 四类 artifact：均未读取、未验证
- readiness：`false`
- T1：`false`
- qualification credit：`0`

本报告故意保持 blocked。当前仓库只有 upstream Linux v6.8 静态参考审计，没有真实完整的 target source tree、UAPI、config 和 build provenance；本合同不会把本机 Ubuntu headers、upstream tag 或合成 hash 提升为 target evidence。

## 外部 manifest 的精确内容

manifest 顶层只能包含固定字段：`schema`、`record_id`、`evidence_origin`、`synthetic`、`target`、`artifacts`。

`target` 必须同时声明：

- kernel release
- 40 位 lowercase source commit
- source tree SHA-256
- UAPI SHA-256
- build-id
- config SHA-256
- 排序且唯一的 required options（至少包含 F8/R008 所需的 seccomp、fanotify、permission 和 x32 ABI 设置）

`artifacts` 必须恰好包含 `source`、`uapi`、`config`、`build` 四个相互不同的相对路径引用；每个引用必须给出 `path`、`bytes`、`sha256`，并与实际读取结果完全一致。source/UAPI/config 的 target SHA 还必须分别与实际 artifact SHA 交叉绑定；config 文件中的 required options 必须逐项匹配。

## 读取和拒绝边界

所有 manifest 和 artifact 只通过 bounded strict JSON / bounded small-file 路径读取：`O_NOFOLLOW`、单 hard-link、regular-file、固定大小上限、stable-FD 前后身份检查。拒绝项包括重复 JSON key、非标准 JSON 常量、path traversal、任意 symlink、hard-link、读取期间 drift、oversize、重复 artifact、partial/missing evidence、synthetic/placeholder digest、upstream v6.8 tag 冒充 target pin 和不匹配的 byte/SHA。

本合同只做 intake/diagnostic；不会启动 kernel、native、worker、GPU 或 queue，也不会修改 gate、ledger、registry 或 `PLAN.md`。

## 后续外部依赖

仍需要外部提供并放入受控 evidence manifest 所引用位置的真实 target source/UAPI/config/build 小文件及其可复核 provenance。依赖满足前，本报告不会变绿，也不会产生 readiness、T1 或 credit。
