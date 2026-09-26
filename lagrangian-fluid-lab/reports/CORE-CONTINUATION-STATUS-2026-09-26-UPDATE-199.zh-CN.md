# UPDATE-199：修复 Core reader bundle standalone 依赖闭包

时间：2026-09-26（Asia/Shanghai）

## 本次推进

对 A8 reader bundle 的现有测试做实际验证时，`tests/test_core_package.py` 出现 3 个 standalone reader/reproducer import failures。根因是 `core_dataset.py` 与 `core_cfd_dataset.py` 已依赖 `core_fsverity.py`、`core_strict_json.py`，但 bundle builder 的复制清单和 verifier 的必需文件清单均未包含这两个模块；因此放在独立根目录、清除 `PYTHONPATH` 的开发包无法启动。

修复如下：

- 新 bundle 使用 `core.reader_bundle.v2`；v2 复制并哈希登记上述两个传递依赖，以及 builder 已列明的全部 Python 入口/模块。
- verifier 的 required-file 集合由同一 `BUNDLE_CODE_FILES` 清单派生，缺少任一文件都会拒绝；v1 不会被误当作包含新版 reader 依赖的有效包。
- `core_benchmark` 的 reproduction code closure 将 `core_fsverity.py` 和 `core_strict_json.py` 纳入哈希绑定。
- 只更新 builder/verifier 与合成测试；历史 v1 bundle、runtime receipts、registry/ledger 均未修改。

验证：`tests/test_core_package.py` **21 passed**；`tests/test_core_benchmark.py`、`tests/test_core_independent_reproduction.py`、`tests/test_core_campaign.py` 合计 **55 passed**；fullfield/halo oracle 两个 suites 合计 **6 passed**；`py_compile` 与 `git diff --check` 通过。

## 完成边界

现有独立根目录下的 F3 reader、bundle verifier 与 reader-reproduction smoke path 已由合成包覆盖通过。这修复了新包的代码依赖闭包，不证明旧 v1 bundles 可移植，也未证明完整数据包在另一台物理主机上完成 reader、全场预测和评分。Core 总门仍未完成；当前真实 cross-host diagnostic 不能升格为 full-product reproduction。
