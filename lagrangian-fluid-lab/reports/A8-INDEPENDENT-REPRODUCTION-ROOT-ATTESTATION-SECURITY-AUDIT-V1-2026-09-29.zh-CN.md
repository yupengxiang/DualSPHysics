# A8 independent reproduction/root-attestation bounded security audit V1

结论：修复后未观察到 metadata-only 绕过；A8 readiness 仍为 blocked。没有伪造 external-host 或 trusted-root receipt，也没有启动 solver、worker 或 GPU。

已修复的可证明缺口：

- independent-readiness 与 trusted-root 报告 validator 曾接受未知 status 配合 `passed=true`、`structural_contract_passed=true`；现已限制为已知 blocked 状态并强制状态、pass 标志和 checks 一致。
- checkpoint provenance 曾可对调用方提供的 source path 做工作目录相对 `lstat`，且未闭合 bundle/registry/checkpoint lineage；现改为不信任 provenance source path，并要求 bundle、registry、dataset SHA、规范化 bundle checkpoint path 及 model/seed/update 对齐。

仍缺少的外部证据：另一台物理机、distinct data root、trusted root review、external host attestation、当前 v2 checkpoint 内容 hash、reader receipt、autonomous prediction receipt 和 scoring receipt。历史 checkpoint/registry 只有 metadata/lstat 身份，不能转移为当前 trusted binding。

测试：目标 A8 35 项通过；A8 全套及不依赖坏 h5py 导入的相关回归 98 项通过。`test_core_independent_reproduction.py` 与 `test_core_reproduction_check.py` 在 collection 阶段受系统 h5py/NumPy ABI 不匹配阻断，未启动任何 workload。
