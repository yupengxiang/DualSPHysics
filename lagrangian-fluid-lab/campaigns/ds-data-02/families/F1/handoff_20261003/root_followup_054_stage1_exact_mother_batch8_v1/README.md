# F1 exact mother batch 8, source-only plan

This scope records eight Stage 1 F1 mother recipes at one coarse resolution. It is a request plan and source contract; it contains no generated XML, BI4, solver output, arrays, typed conversion, or ParaView product.

The two immutable source templates are the known working coarse definitions from preparation 027:

| mechanism | head heights (m) | DP (m) | template definition SHA256 | canonical condition SHA256 |
| --- | --- | ---: | --- | --- |
| ECC | 0.11, 0.13, 0.15 (existing anchor), 0.19 | 0.01 | `2b86359cff38e9eea2c0c2d09e84e3647ea25d74e6783105b293e0622a8ec157` | `687c069f836dd81b3c4c85ea6f977f9f2775debea01d3657b81356801ced71d3` |
| DUAL | 0.22, 0.26, 0.30 (existing anchor), 0.34 | 0.02 | `b16c9a83a3d711fcc11939ca5418d62fbc1ae0fa4e6fe13f48613177cbe9914e` | `feb710be76c89fb67074b1bbbf6c9c22869652ce5760c4d7e4721187b4d580bf` |

The intended materialization changes only the `size.z` attribute of the existing fluid cell-centre `drawbox` identified by `cmt="v1 fallback controlled fluid cell centres"`. The value is `H0 - dp`: ECC target values are `.10`, `.12`, `.14`, `.18` m; DUAL target values are `.20`, `.24`, `.28`, `.32` m. Tank, obstacle/divider, fluid footprint and origin, fluid marker, EOS constants, and native execution step flags stay bound to the template source hashes. The recipe files do not materialize these edits.

The resulting fluid counts and masses are predictions for the later GenCase and initial-QA gate:

| recipe | predicted grid `(x,y,z)` | predicted fluid particles | theoretical volume (m³) | theoretical mass (kg) |
| --- | --- | ---: | ---: | ---: |
| ECC H0=.11 | `(40,67,11)` | 29,480 | 0.02948 | 29.48 |
| ECC H0=.13 | `(40,67,13)` | 34,840 | 0.03484 | 34.84 |
| ECC H0=.15 | `(40,67,15)` | 40,200 | 0.04020 | 40.20 |
| ECC H0=.19 | `(40,67,19)` | 50,920 | 0.05092 | 50.92 |
| DUAL H0=.22 | `(50,50,11)` | 27,500 | 0.22 | 220 |
| DUAL H0=.26 | `(50,50,13)` | 32,500 | 0.26 | 260 |
| DUAL H0=.30 | `(50,50,15)` | 37,500 | 0.30 | 300 |
| DUAL H0=.34 | `(50,50,17)` | 42,500 | 0.34 | 340 |

Every GenCase and initial-QA request has `launch_allowed=false`, `production_approval="none"`, and no actual artifact hash. A future authorized run must create a height-specific definition and binding, hash them, run the known preparation path, and perform new initial QA. The existing anchor BI4 is provenance only; this scope makes no BI4 equality claim and does not add an independent case count.

The exact source contract retains the source literal `<setshapemode>dp | actual | bound</setshapemode>` byte-for-byte. This scope neither rewrites it nor labels it invalid. Boundary support is bound by source bytes and is not translated into a layer-count assertion.

The prior negative records remain in the plan: the historical ECC H0=.30 and DUAL H0=.55 mothers are retained as failures. No zero-loss or eliminated-overtopping result is inferred for these planned lower-head recipes. No numerical precision acceptance or user visual approval is recorded; Root owns the later full-animation review and launch decision.

The source-only API checks are in `tests/test_exact_mother_batch8.py`. Rebuilding the deterministic plan uses:

```bash
python3 scripts/build_exact_mother_batch8.py --check
```
