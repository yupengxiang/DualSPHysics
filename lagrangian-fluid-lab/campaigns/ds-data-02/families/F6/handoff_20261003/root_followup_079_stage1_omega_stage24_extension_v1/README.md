# F6 fresh079 stage24 omega extension (source-only)

This package proposes eight new DP0.025 angular-release values strictly inside the already registered `[0.25, 2.0]` scale interval: `0.30, 0.40, 0.60, 0.90, 1.10, 1.30, 1.60, 1.90`. The confirmed F6 omega grid has eight values including the source mother, two endpoints, and five internal values. This batch projects the omega grid to 16 of the stage24 target 24; eight values remain for a later source-only extension. No count increment is claimed here.

Every new XML source is copied from the reviewed DP025 recipe and changes only `casedef.floatings.floating.angularvelini` to `scale * [0.08, 0.12, 0.06]`. The actual mother time recipe remains `TimeMax=12`, `TimeOut=0.05`, with 241 expected frames. The source retains free 6DOF, zero initial fluid velocity, `Mk=60`, `type=2`, center `[2.4,1.2,1.08]`, physical mass 128 kg, native support 256 kg, and masspart 0.015625 kg.

## Root execution order

1. Review and enable each `gencase/requests/*.json` through the strict CPU runner. Bind the actual 3D GenCase XML/BI4/receipt into `qa/initial-native-qa-binding.json`; future hashes are intentionally null here.
2. Enable `qa/requests/stage24-initial-native-qa-request.json` through strict CPU PartVTK. This worker writes its own private outputs; its historical evidence list has exactly the two immutable QA019/semantic020 records. Particle V0 is not angular-state evidence.
3. Bind the actual aggregate QA receipt/index and per-case reports, then enable each qualification request through Root146 (`root_stage1_f6_actual_qualifications_strict_entry_146/launch.py`). The command is the reviewed mother solver recipe with only the fresh GenCase prefix and attempt output substituted.
4. After native state0 FloatingInfo corroboration and full 241-frame native completion, enable the eight unchanged NVMe conversion requests. The CPU conversion cap is 2, NVMe staging peak is 24 GiB, and the free-space floor is 100 GiB.
5. Bind actual typed receipts/reports before enabling the XMF requests. XMF output goes to `{attempt_root}/xdmf`; render output goes to `{attempt_root}/render`, so the strict runner receipt directory remains independent and empty at worker start. Root023 computes native bounds across all saved frames; no fixed camera/domain bounds are embedded.

Run `python3 validate_source_contract.py` or `python3 workers/assemble_stage24_requests.py`. Both are metadata/XML checks only and do not invoke a solver, converter, decoder, PartVTK, or renderer.

All requests are disabled and all future payload/output hashes are null. This package makes no GenCase, native QA, state0, typed, XMF, visual, Q-N, precision, production, or acceptance claim.
