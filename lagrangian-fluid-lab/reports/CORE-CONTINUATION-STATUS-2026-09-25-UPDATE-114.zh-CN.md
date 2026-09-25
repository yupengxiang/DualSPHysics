# Core 计划续推状态 UPDATE-114

日期：2026-09-25（Asia/Shanghai）

## 本次推进：统一 Core path-backed JSON 输入边界

将 UPDATE-113 的 bounded strict JSON 实现抽到 `scripts/core_strict_json.py`，planner 保留原 API/可配置 64 MiB 上限并复用共享实现；新增接入：

- `CoreDataset` path-backed manifest；
- CFD adapter 的 path-backed source manifest 与外置 prepared-record JSON；
- `core_learning._manifest_path()` 保留最终目录项，避免 CLI 在 reader 前先 `resolve()` 跟随 manifest symlink。
- shared helper 纳入 planner、admission auditor 与 capacity-evidence 的当前 formal learning source closure；闭包 verifier 明确把既有 v5/v6 八文件收据判作历史过期而 fail closed，不改写历史收据。历史 v2/v3 diagnostic preprofile snapshots 继续按其当时冻结的八文件清单验证。

共享 reader 对最终 symlink 使用 no-follow、非阻塞方式打开，并只接受稳定 regular-file FD；读取有 64 MiB 界限，解析拒绝 strict UTF-8 失败、嵌套重复键、NaN/Infinity、float overflow、超过 128 位的 JSON integer 和非 object 顶层。CFD adapter 的 `source_manifest_sha256` 现绑定 parser 实际使用的 raw bytes，不再在 parse 后重新打开路径；diagnostic Mapping 输入保持兼容但仍不构成 trusted capability。

回归覆盖 Core/CFD manifest 重复键、非有限数、过长整数、非法 UTF-8、可配置字节上限、symlink、prepared-record 重复键、source manifest 读后路径替换与直接 script CLI 的共享模块导入。planner、learning、Core dataset、CFD dataset、admission-readiness 五组 **144 passed**；扩展 closure/admission/capacity/preprofile 与历史 source-closure suites 合并 **76 passed**。admission auditor 与 capacity evidence 直接复用 planner 的 required-file tuple，避免 closure drift。修改脚本 `py_compile`、planner/auditor/capacity 直接 `--help` 与 `git diff --check` 通过。HDF5 仅由现有/新增合成测试在临时目录生成和读取；没有访问生产轨迹或 one-shot 数据，没有运行 solver、GenCase、worker、GPU 或队列。

## 边界

这是通用 bounded serialization 与 raw-byte reference binding，不认证 manifest/prepared producer、可信 root、runtime/import identity 或同 FD/snapshot 的 HDF5 worker。旧 Mapping/path readers 仍只作 diagnostic；V13 trusted reader/supervisor/broker/fs-verity/runtime closure、F8 per-case provenance/T1 和 Core T1/T2 均未完成，资格信用仍为零。
