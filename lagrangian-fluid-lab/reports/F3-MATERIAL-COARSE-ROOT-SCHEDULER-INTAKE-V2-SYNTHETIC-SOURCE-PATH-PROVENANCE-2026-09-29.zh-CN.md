# F3 material coarse v2 source path provenance synthetic contract

- 状态：`synthetic_only_non_authorizing_source_path_provenance_contract`
- 候选：`CORE-F3-MATERIAL-COARSE-s2`
- 输入来源：`synthetic_fixture`；synthetic-only=`True`

## 审计结论

v1 只对 source HDF5 最终节点做 lstat，没有拒绝 parent symlink，也没有复用 bounded input 的 single-hardlink 规则。
v2 侧车补充 root-relative path、逐组件 symlink、realpath containment 和 single-hardlink 检查。

- parent symlink 缺口复现：`True`
- parent symlink 拒绝：`True`
- root symlink 拒绝：`True`
- realpath containment：`True`
- single-hardlink 拒绝：`True`

## 非授权边界

该报告只描述 synthetic contract；不读取 production source HDF5，不启动或控制 solver/worker/GPU/queue，
不写 registry、ledger、denominator、gate、completion 或 PLAN，formal/T1/T2/qualification/credit 恒为 false/0。

## 合成用例

- `synthetic_clean_source`：`data/clean/source.h5` → `source_path_provenance_closed_non_authorizing`
- `synthetic_parent_symlink`：`data/alias/source.h5` → `blocked_source_path_provenance`
- `synthetic_source_hardlink`：`data/alias/source.h5` → `blocked_source_path_provenance`

该 v2 侧车没有修改 v1；未来接入必须继续保持 fail-closed。
