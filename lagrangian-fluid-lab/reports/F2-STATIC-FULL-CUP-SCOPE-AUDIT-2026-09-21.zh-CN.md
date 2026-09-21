# F2 full-cup static volume-hold 只读范围审计（2026-09-21）

本报告复用现有的 `scripts/f2_static_full_cup_cpu_preflight_audit.py` 和
`campaigns/core-v1/evidence/f2-static-full-cup-cpu-preflight-v1.json`。本轮只读核对
candidate、15-cell 设计、v4 CPU/native closure、静态 anchor 和 H1/H2 负证据；没有启动
GenCase、native decoder、solver、GPU 或 queue，也没有写入 registry、ledger 或 queue。

结论是：这个候选满足“输入闭合审计”契约，但没有满足也没有声称满足 F2 T1 资格契约。
v4 的 15/15 行各自有新 Definition、zero-angle motion、BI4、decoded native preflight 和
23 项 hash closure；固定分母仍为 15。full-cup static anchor 是 q=.5、dp=.0075 的历史
静态 canary，只作为前置证据，明确排除在分子之外。

## 审计判定

| 项目 | 判定 | 证据 |
|---|---|---|
| candidate 身份 | 通过 | `F2_static_full_cup_volume_hold_x_v1`，`qualified=false`，`qualification_claim` 为 `none;` |
| 15-cell 设计 | 通过 | 13 个 spatial 行（q=0/.5/1 与 held-out q=.25/.75）+ 2 个 temporal 行 |
| v4 CPU/native input closure | 通过 | 15/15 prepared，15/15 preflight，0 failed，0 unresolved；每行 closure 23/23 |
| 固定分母 | 通过 | `registered_cell_count=15`；失败/未完成行保留；`survivor_renormalization=false` |
| anchor 排除 | 通过 | anchor case identity 不在 15 行中；matrix closure 不含 anchor trajectory；`anchor_trajectory_reuse=false` |
| 资格声明 | 通过 | candidate、admission、matrix audit 和 read-only audit 均为 `none;` 或等价的 CPU-only claim |
| T1 资格 | 未满足且不应满足 | 没有 15 行 solver/runtime products；scope review 为 `prerequisite_only`，T1 credit=0 |

现有审计产物的状态是 `ready_for_root_canary_review`，其含义是“可另行请求一个单独的
cell-0 root review”，不是允许提交矩阵，也不是资格通过。

## 固定 15 行与输入绑定

下面的 prepared/preflight SHA 来自 v4 `matrix-preparation-audit.json`。每一行均计入固定
分母；这里的 `passed` 仅表示 CPU/native 输入门通过，不是 scientific numerator success。

| index | case | q | dp (m) | prepared SHA-256 | preflight SHA-256 |
|---:|---|---:|---:|---|---|
| 0 | `CORE_F2_static_full_cup_volume_q0p00000000_dp0p010000000000_spatial` | 0 | .0100 | `b317b9a6cc159652a45bdb9ec4aa29acba7d7fcf3886580102aff8fd55d90223` | `19bfaabc8559352079a2cbcfafe0ce06a76cdbab41b8676ce4047400be7eab5f` |
| 1 | `CORE_F2_static_full_cup_volume_q0p00000000_dp0p007500000000_spatial` | 0 | .0075 | `12b1a7b46e4ad690a17fbdf5b8493a78a851875b2aca2de66ee8a1848ffb311a` | `ccf8d38312dac7914fda16ce6ce6dc0ab9e6271a43ad2ecec707c6093b29f686` |
| 2 | `CORE_F2_static_full_cup_volume_q0p00000000_dp0p005000000000_spatial` | 0 | .0050 | `6cac6f9dcd1102ef4395511aeed96b5c0622a0e4c2ba198bca8bed86a25ea2ca` | `81e638c72a3187385f3f389e346743a145c3dcf37019869880b208519c87a360` |
| 3 | `CORE_F2_static_full_cup_volume_q0p50000000_dp0p010000000000_spatial` | .5 | .0100 | `f01d06015d5492f3329ad2379e4801b786ef2f48100bac5ec1488c2cf6d75bbe` | `0faf8f3370879b58b3c73111d514918ec16e19f780143a6ffb31254be1210666` |
| 4 | `CORE_F2_static_full_cup_volume_q0p50000000_dp0p007500000000_spatial` | .5 | .0075 | `ac4226090bf9646dd0e42f2b08895c70f9a36156514f0dcee31ef78ebeda1216` | `d34475c851b8ecc56d1db7680c86742b1417aa93e6105e6da6c4732884fea546` |
| 5 | `CORE_F2_static_full_cup_volume_q0p50000000_dp0p005000000000_spatial` | .5 | .0050 | `6d278bb0ae49ba1f97ae41c3d933c217a33e0d5720b367f1b2e68221a6b8b11d` | `bfabcf5cb80818f9a80b20b3b94035ffa219ad9188d5a5b2e75882da2ed9e9ae` |
| 6 | `CORE_F2_static_full_cup_volume_q1p00000000_dp0p010000000000_spatial` | 1 | .0100 | `7ac3a5a1a595a6ec6f0a5ca57fb3af36ead088f16c2232d7f7841d8c1df4f451` | `1ddc092b250d51343da88a7bac20e72cdbff27254f7f6b9c284bdd1aa85f3c46` |
| 7 | `CORE_F2_static_full_cup_volume_q1p00000000_dp0p007500000000_spatial` | 1 | .0075 | `9d0810b4681f65b9cc39b7e2acb61f42e23791c9eb2a689fdc485c470029c22b` | `7c980d532b0974c6596a238b67d1d0469d42476f227f58d84d54510e0711f7a9` |
| 8 | `CORE_F2_static_full_cup_volume_q1p00000000_dp0p005000000000_spatial` | 1 | .0050 | `4bc74a36753d7c08005adb2ec27f323f907477e214c61ae5af41b436c6aa9eec` | `83e1de20b2a42a5fd8caff8022c0d28be6d51053b6487994f0b75f631783ac28` |
| 9 | `CORE_F2_static_full_cup_volume_q0p25000000_dp0p007500000000_spatial_held_out` | .25 | .0075 | `7b26b4f897e5a03cf0064ed85d964375857076cc36883ce431cbcd8b39d648ac` | `3b5b2121c1b164f635df34aae6553e1548b5999fe4411218b584edb5cc18c133` |
| 10 | `CORE_F2_static_full_cup_volume_q0p25000000_dp0p005000000000_spatial_held_out` | .25 | .0050 | `209ef619e3f087da70936abfb78ed7a0cd922be29a0baa52d5a462099d8aa979` | `b2dd23b7acf9b48669bd3d315cb9e6454f1f31f828e9c659fc065c6df1c7f4dd` |
| 11 | `CORE_F2_static_full_cup_volume_q0p75000000_dp0p007500000000_spatial_held_out` | .75 | .0075 | `774eac194d4b000e6290cec2612609a51995b07e6e61fb32f3b3ee39d4d30bec` | `f8903d9385c05d1b342f1f004774db7318b1559bcefe2de5492466ddf1842f88` |
| 12 | `CORE_F2_static_full_cup_volume_q0p75000000_dp0p005000000000_spatial_held_out` | .75 | .0050 | `551d1b583d02626813ad817b53d381719d1f33ce6152ee9c7b1beec79eff3ff3` | `1784a60ac6b52457345f7f6eab371455d77daf016e72175e9f234b02397b8325` |
| 13 | `CORE_F2_static_full_cup_volume_q0p50000000_dp0p007500000000_internal_time` | .5 | .0075 | `5bf83b2b6f7914630bada1b14edaf813411ac8c8347ba20443ecb37635ba0b95` | `bae8e2bed7c4023d63a7a9f63ad9ab4e1de6777d6280317c75ed0691b20deade` |
| 14 | `CORE_F2_static_full_cup_volume_q0p50000000_dp0p007500000000_native_output` | .5 | .0075 | `635733e970962369d4a9736f418881fb17da5ea6de2b087f456994324e189dd2` | `9e1cbec2db35e632cc6bcc79d6322189389e4c37208fed442a5a1d425666fe74` |

The v4 matrix report also binds the candidate (`fcbaa77fe28c2ec43a4fd7eb28023555d15a520439f31b01151600cc0342c26f`), matrix report (`f5bfacfc38b700aa43f7bc9b2db3cacfbd126666419b3eaa8422d45ff2056746`), and matrix audit (`bc44fbf64aff429eb9ddb5e71117548413e7db047ceabbee627a6fe0312ecc25`). The existing read-only CPU/native audit is bound by `6f5fbe8bef63db9f2cb64c26698bd27a3b597d03763a4995bfa71b5315010115` and independently verifies each row's 23-item closure.

## Static anchor and H1/H2 relationship

The historical full-cup static anchor is hash-bound as follows:

| input | SHA-256 | observation |
|---|---|---|
| static anchor integration | `5d8cc041fa63f80401105e1d6884a0c77004326f6c85f6309e9bd82df0dfc589` | hard pass, complete 0.60 s window, settled, 54,720 native fluid particles |
| anchor prepared manifest | `2bb1dac4bef30bea2926184641c9d4f3a18895b5b9468ac86b14cbbe28f256c7` | native DBC, zero initial velocity, no mass rescaling |
| anchor static preflight | `8e6d30ccf7ea3c1e4f1e56de400411671590f6696b7c4d338cbd1ff3ada1142d` | IDs/finite/inside/no-overlap/mass gates pass |
| candidate card | `fcbaa77fe28c2ec43a4fd7eb28023555d15a520439f31b01151600cc0342c26f` | anchor claim is static nominal only |

The anchor metrics are p95 speed `0.0366636326 m/s`, KE/initial-potential `0.0001917994`,
outside-cup mass fraction `0`, retention `1`, and mass error `-0.0216147489`. These metrics are
supporting static evidence only. The integration record exposes output hash checks as booleans,
but it does not enumerate trajectory path/byte/SHA bindings; a future scientific package would
need that explicit output closure before treating the anchor as a reproducible runtime product.

H1 changed only the boundary formulation to mDBC and consumed one repair class. Its retained
negative evidence is `bbb97817955782e787a844300e3756af248d9cc49e7ecbb43b6275f7dd6de166`:
the cell-0 runtime reached the requested horizon but had `hard_integrity_pass=false`,
`event_window_complete=false`, 10,433 endpoint-violation particle frames, 1,263 saved-frame
chord crossings, and 1,094 affected fluid IDs. The other 14 rows were not expanded, and the
same H1 input must not be retried.

The later H2 mDBC static-hold audit contract (`61f9e214c86bc7ed5c7e9b35e117c8395191af1001c2b5742b0ca9209154f4e4`) records 8/8 scientific static failures and zero credit. It is not an available repair for this candidate. The v4 DBC input closure therefore remains useful as a baseline input audit, while H1/H2 runtime evidence shows why CPU/native pass cannot be promoted to runtime qualification.

## Gaps and bounded next step

The remaining gaps are explicit:

1. There are no solver trajectories or event observations for the 15 rows. The matrix has no jobs, queue submission, registry entry, ledger credit, or qualification claim.
2. The scope review is `prerequisite_only`: fixed zero-angle holding does not establish prescribed motion, receiver transfer, overflow, or dynamic F2 T1 behavior.
3. The candidate card remains a design card (`design_only_unprepared`) even though a separately hash-bound v4 CPU/native preparation report exists. This is a version-layering gap to reconcile in root review; it is not permission to mutate the card or denominator.
4. The static anchor's integration receipt needs per-output trajectory path/byte/SHA closure if it is ever used in a scientific package. Its current evidence is sufficient for the static anchor observation and for excluding the anchor from the future numerator.

The only bounded next action supported by this audit is a separate root review for exactly one
fresh-output DBC cell-0 static canary, with zero credit and a new job/output identity. That review
must keep the fixed 15-row denominator, preserve the H1 negative row and H2 negative lineage, and
leave solver/GPU/queue/ledger/registry actions closed until explicitly admitted. It must not
retry H1, expand H1 to the remaining 14 rows, or treat this static candidate as a third T1 family.
If a true independent repair is required, root must first review a new physical/geometry
hypothesis with a new scope/case/output identity; this audit does not authorize one.

## Validation

The reused audit implementation and its targeted tests are the existing read-only closure check:

```text
pytest -q tests/test_f2_static_full_cup_cpu_preflight_audit.py
```

The test contract asserts 15/15 closure, fixed denominator retention, anchor non-reuse,
zero-credit execution controls, and tampered-row failure retention. No computational executable
was launched while preparing this report.

