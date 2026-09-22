# F2 接液/溢流堰候选路线审计报告

日期：2026-09-20。路线：`F2_receiver_overflow_weir_v1`，修订：`F2_receiver_overflow_weir_mdbc_v1`。

## 候选机制

初始状态是固定上游连续液库，重力驱动液体越过外壳内部的有限高度堰顶，进入同一封闭外槽内的下游有限接液区。q 只映射堰顶高度 `h_c=0.20+0.12q m`，不改变时长、观察窗、外槽或观察规则。该路线没有旋转杯、DBC duration、悬空障碍物、波源或 run-up 测线，因此不复用 F1 G1 和既有 F2 dynamic DBC duration 的输入 lineage。

## 输入版本判定

- `generated_v1`：离散初始质量约高于连续源质量 6.35%，超过 3% gate；废弃，zero credit。
- `generated_v2`：离散初始质量约高于连续源质量 6.48%，超过 3% gate；废弃，zero credit。
- `generated_v3`：离散初始质量约高于连续源质量 6.35%，超过 3% gate；废弃，zero credit。
- **最终仅绑定 `generated_v4`**：q=0.5，堰高 0.26 m，dp=0.0075 m。GenCase code=0；boundary=245,667，fluid=228,480，total=474,147；zero normals=0；native IDs 唯一、数组有限、初始流体速度为 0。连续源质量 96.768 kg，native 离散质量 96.39 kg，相对误差 -0.00390625，质量门通过。

## 固定矩阵和失败分母

15 行矩阵已经冻结但没有 materialize 或 submit：13 个 spatial 行（q=0/0.5/1 与 held-out q=0.25/0.75）加 2 个 q=0.5、dp=0.0075 的 internal-time/native-output 行。当前 `executed=0`、`passed=0`、`event_censored=0`、`unattempted=15`、`matrix_credit=0`。`qualification_claim=none`，`qualified=false`，CPU/native preflight 不产生 T1 credit；任何 solver failure、hard-integrity failure 或 event censoring 都必须留在分母。

## 执行边界和 blocker

本候选只完成 CPU GenCase、BIFileInfo 和 native BI4 decode。**没有执行 solver、GPU、queue、ledger 或 registry，也没有生成 runtime product。不得运行 solver。** Root-review-only job spec 已设置 `submit_allowed=false`。

当前 blocker 是缺少经 root 审查的 receiver/crest runtime adapter 与 crest-crossing/receiver-contact observer。只有在 root 接受新物理机制、审查 v4 hash-bound 输入并明确授权一个 protected anchor 后，才可讨论 runtime adapter 和后续矩阵；本报告不授予任何运行授权、qualification 或 T1 registration。

## 审计文件和 v4 hashes

- 候选卡：[candidate-card-v1.json](../candidate-card-v1.json)
- 15 行矩阵：[fixed-matrix-v1.json](../fixed-matrix-v1.json)
- 失败分母：[failure-denominator-v1.json](../failure-denominator-v1.json)
- lineage：[lineage-clarification-v1.json](../lineage-clarification-v1.json)
- CPU/native preflight：[cpu-native-preflight-v1.json](../cpu-native-preflight-v1.json)
- root-review-only spec：[root-review-only-job-spec-v1.json](../root-review-only-job-spec-v1.json)
- route audit：[route-audit-v1.json](../route-audit-v1.json)

v4 定义 XML SHA256：`dc5908b2e88d0384fc01801ce043ec389052431f80271e766b1571d9168bae21`；`gencase-v4.log`：`66f13a6a204554912038f3f70d6f4b8b710cac1d1684304cf58d7b82e56933d8`；native `.bi4`：`5f7eb737b08009d2c8b899e128f6d75fd243d9e78131cbbc8addd73a6e720292`；native metadata：`09a38f51705160c0c6321a01351576faacae44fe655ed8491a47e0884199fc55`。

## Adapter contract follow-up

Root added the read-only adapter [core_f2_receiver_overflow_weir_v1.py](../../../../../scripts/core_f2_receiver_overflow_weir_v1.py). It verifies the v4 native input, all 15 denominator rows, the zero-credit policy and the v2 root-review hash closure. It also exposes pure crest-crossing and receiver-contact observers for supplied trajectory states; it does not read future CFD state, run a decoder, start a solver, or mutate queue/ledger/registry.

The adapter contract preflight is [adapter-contract-preflight-v1.json](../adapter-contract-preflight-v1.json), SHA-256 `157a0f99a5ca79a3f90d6ee8d6e6f7c6dd9330093113b2b2898f6779e2cdfc7a`; the adapter SHA-256 is `cb21fffbf8de336361e451504e1ea81f580250680d124b1847d0fffc74673721`. The versioned root-review spec [root-review-only-job-spec-v2.json](../root-review-only-job-spec-v2.json) SHA-256 is `94d645b571e723515bbb60adee32e726f8bd097012deb8bc290e834a9ef029f8` and keeps runtime preparation, solver launch and queue mutation disabled. The pure observer contract passes synthetic crossing/contact tests only; no physical trajectory result is claimed.

The adapter-only root review [root-review-adapter-contract-v1.json](../root-review-adapter-contract-v1.json) SHA-256 `742e41517ad20ae679a4f435af763e83a2c75f2a3462d7eb748f20a5f3c01f69` accepts the static contract but explicitly sets `authorized_anchor=false`, `authorized_runtime_preparation=false`, and all solver/GPU/queue/ledger/registry controls to false or zero. The next review must bind a solver-integrated prepared manifest and finite-weir hard audit before any anchor can be submitted.

## Prepare-only manifest and HDF5 hard-audit follow-up

The root implemented [f2_receiver_overflow_runtime_v1.py](../../../../../scripts/f2_receiver_overflow_runtime_v1.py) as a **proposal-only** preparation and post-processing layer. It resolves the hash-bound v4 native anchor, records the finite outer tank, open top, closed faces and finite internal weir, and retains the native `rho*dp^3` mass without rescaling. The decoder is used only for a CPU input probe; the temporary decoded directory is not published as a reusable path.

The prepared proposal [runtime-prepared-proposal-v1.json](../runtime-prepared-proposal-v1.json) has SHA-256 `98f63576ef981dd554ed8dd9a1103d56334c154dd622893f877e9d88dffb535e`; the implementation has SHA-256 `b3b18d275f16cb71bfe59c2383433f00b712d4e5486b600ef49ee2b6acb360fa`. Its status is `prepared_proposal_not_runtime_authorized`, with `qualification_claim=none`, `matrix_credit=0`, and solver/GPU/queue/ledger/registry controls all false or zero. The proposal binds the candidate, matrix, failure denominator, lineage, CPU/native preflight, v2 root-review spec, pure adapter, solver binary, decoder and v4 native artifacts. It deliberately retains `root_review_required=true` and does not contain an executable `argv`.

The derived [anchor-job-proposal-v1.json](../anchor-job-proposal-v1.json) has SHA-256 `0dccdeb7d5b445ccd9176bdf0d824185d4b1eff93f2bdb3ece95ce4d703703ca`. It is an immutable one-anchor proposal with `submit_allowed=false`, empty `argv`, no solver/GPU launch and no queue/ledger/registry mutation. It is not a queue job and has not been submitted.

The same module audits a supplied HDF5 trajectory against finite closed faces, the internal weir obstacle, saved-frame chord crossings, finite values, particle identity and mass closure, then applies the crest-crossing and sustained receiver-contact observer. The audit receipt is post-processing only and always reports zero qualification credit. A synthetic complete trajectory contract passed together with the existing candidate tests: **8 targeted tests passed**. No solver, GPU, queue, ledger or registry operation occurred, and the 15-row matrix remains `0/15` with zero credit. A future solver-integrated implementation still requires a new root review before any runtime preparation or anchor submission.

## Exact-one-anchor runtime and terminal negative result

After the proposal audit, root approved exactly one protected matrix row in [root-review-one-anchor-v2.json](../root-review-one-anchor-v2.json), SHA-256 `cfb561d4fe8f542bb46088624cd2a42d49df5bfd19bbbd73bda910df34511ccf`. The review binds the candidate, all 15 rows, failure denominator, lineage, v4 native input, adapter, preparation code, solver, decoder and solver worker; it authorizes only row 4 (`q=.5`, `dp=.0075`, `spatial`), keeps `matrix_credit=0`, forbids registry and matrix mutation, and disallows scientific retries or pre-anchor horizon extension.

The protected job [anchor-job-v2.json](../anchor-job-v2.json), SHA-256 `45b78e7d4a463f8a831c7af23a1c2cb7c5386be9d28ea25e40a13dbac8b5b035`, was submitted to the persistent Ada queue. The first job `...-001` failed before solver launch because of a worker field-lookup bug; that infrastructure receipt is preserved. The v2 job `...-002` is the single allowed infrastructure retry (`retry_of` is explicit), completed the solver and conversion, and carries no duplicate scientific credit.

The completed attempt ran `151` saved frames through `1.500016 s`; solver wall was `84.260696 s`, queue wall `313.262003 s`, peak sampled GPU `558 MiB`, peak sampled process tree RSS `2035.25 MiB`, and converted trajectory SHA-256 `fe337808de19c091ebfbc1ae4bdc76ad3e4607d9c32f3ac8c6900e02589c66a6`. It is a **scientific negative anchor**: the registered horizon was reached, but hard integrity failed with `74` closed-wall endpoint particle-frames, `1,490,604` internal-weir penetration particle-frames, `1,490,609` saved-frame chord crossings and maximum relative mass change `0.0004989495798319865`. Receiver contact first exceeded 1% at `0.4100556764 s` and remained sustained for `1.0899899818 s`, but the registered crest-crossing observer found no qualifying crossing, so `event_window_complete=false`.

The immutable negative receipt [f2-receiver-overflow-weir-anchor-negative-evidence-v1.json](../../../evidence/f2-receiver-overflow-weir-anchor-negative-evidence-v1.json) has SHA-256 `844bb4c6e41b1000205b875d8efd540dd8c0438131c74f1b2324168cdb53d608`; its collector is [f2_receiver_overflow_negative_evidence_v1.py](../../../../../scripts/f2_receiver_overflow_negative_evidence_v1.py), SHA-256 `baaa48d65e174586a04091c3593dea9854691cb567d6d28bc478daa833725e06`. The unchanged preregistered matrix remains the source of truth; terminal view [terminal-matrix-v1.json](../terminal-matrix-v1.json), SHA-256 `8089ceb988ee8ed0e51bfb135939affe237741478f368cf7d6acc4f1367e12e4`, records row 4 as `failed_hard_integrity_and_event_censored`, with `executed=1`, `failed=1`, `event_censored=1`, `unattempted=14`, and zero credit. No other row was launched, no threshold was relaxed, and no registry/ledger/scientific qualification mutation occurred. This route cannot enter the third T1 family; a future repair must be a new preregistered hypothesis and cannot retry this scientific input.
