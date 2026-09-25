# Core 计划续推状态 UPDATE-115

日期：2026-09-25（Asia/Shanghai）

## 本次推进：收齐 formal gate JSON 文件入口

将 UPDATE-114 的 `core_strict_json.py` reader 扩展到其余 `core_formal_*` 脚本的 path-backed JSON：formal admission、capacity evidence、readiness、release candidate、launch contract、CPU resource dry-run、graph capacity probe，以及版本化 source-closure admission v5/v6 verifier。路径保留最终目录项，让 no-follow 打开能够拒绝 symlink；输入限定为稳定 regular file 与有界 strict JSON object。path-backed reference 的 SHA-256/bytes 现在使用同一次解析所消费的 raw bytes，不在 parse 后重开文件。

graph capacity probe 的 manifest binding 也改为读取、严格解析并哈希一次，然后将同一 payload 交给 `CoreDataset`，消除了先校验一份 manifest、随后由路径重新加载另一份的窗口。readiness 的 source bindings 增加共享 parser 本身。未改写或重发历史 JSON 回执；旧闭包版本仍以其原有数据按当前 required-file 清单 fail-closed。

对 formal admission、capacity、graph probe、readiness、release candidate、launch contract、resource dry-run、source-closure v5/v6 admission 与历史 preprofile 定向 suite 共 **70 passed**。九个 formal CLI 的 `--help`、相关模块 `py_compile` 和 `git diff --check` 通过；静态搜索未发现 `core_formal_*.py` 中剩余直接路径 `json.loads/read_text` 入口。此前一次测试命令引用了不存在的测试文件名，没有启动测试；改用仓库实际文件名后重跑通过。

## 边界与未完成项

本次没有运行 32k CPU dry-run 或 graph probe 工作负载，没有运行 solver、GenCase、worker、GPU 或队列，也没有读取生产 HDF5。测试仅覆盖 metadata、合成 JSON/torch checkpoint fixture 与现有历史收据。共享 strict JSON reader 只建立序列化和文件读取边界，不证明 producer、可信 root、runtime/import identity、HDF5 同 FD/snapshot 或 supervisor/broker 能力。formal jobs 仍为 0、资格信用仍为零；V13 trusted reader/runtime closure、F8 的 15-case T1、第三个独立 T1 家族、Core T1/T2 与全部计划任务仍未完成。
