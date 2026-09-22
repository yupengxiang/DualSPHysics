# F3 baffle normals v2 runtime canary — 2026-09-20

The normals-aware v2 input closed the original solver compatibility gap: GenCase produced a hash-bound `*_hdp_Actual.vtk`, the native BI4 contained a complete `BoundNor` field, and DualSPHysics loaded the normal configuration and completed the requested 8.35 s solver window. The single Ada diagnostic canary nevertheless failed the runtime hard and event audits.

## Bound input

- Prepared: `f4ba57f1ceeeaa76b657acfc6f444402cf356830b4cedeb0ed0a1730bd42f17c` (`anchor-q0p5-dp0p0075-normals-v2c/prepared.json`).
- Candidate: `4ecd094855b635afdb412fe94c42148a2a5ef8ec0de1c1dc416d9c7c1d29d9f7`; matrix: `5f2478ebfa446badc895e806c1eb4a55e35fc2fc3cbf9b7980549db74ceb9696`; denominator: `0c9f988ce3d917de540949eb28ca61b563a5fc5f0fdaf5763ec1e745354de5da`.
- Root review: `1df5dfacd5ccaa6df52894326bb684c4eb7b6d5b55fad64363ca6fb08b992208`; job: `8002daa39ea1f358f7bb10ec01bb8ae5c6ec0f6afd6c420121169b05d6857bec`.
- Adapter profile: `efb89f5ca3a1e4c32ae8e7d74d7a805393c1c7c8952a3103b3675938a132b47c`; preflight tests: `13 passed`.

## Execution

- Receipt: `400ce32b2ee711cdbe95e0fc9cfe0ffbcc2d9310a41efcda6b2233583808e62c`; attempt `20260920T183024-c881fc1149e8` under the existing Ada coordinator.
- Allocation: GPU 0, `GPU-3dd8e277-f7e1-3893-292a-5928ea229599`, reserved 9831 MiB; wall 281.448 s; child CPU 283.176 s; peak RSS 735.7 MiB; GPU reservation 0.078179949 h.
- Solver return code was 0 and the native conversion produced 836 frames through 8.35001594 s without interpolation.

## Audit result

- Hard integrity: **failed**. Fluid validity was incomplete; outer closed-face and internal-baffle penetration checks failed. The first baffle penetration occurred at 0.0100356 s; saved obstacle chord crossings were 20,990. The solver log reports 26,732 of 131,403 fixed particles without normal data and later reports more than 10% of particles excluded.
- Time window: passed. Saved cadence passed with maximum error 3.60225e-05 s and the requested horizon was reached.
- Exchange event: **failed**. Baffle encounter passed; reverse exchange count was 5, forward exchange count was 0, so `event_window_complete=false`.
- Matrix credit remains **0**. Scientific registry, matrix, and denominator documents were not mutated; T1 was not registered.

The v1 `No normal data for mDBC` blocker and receipt remain unchanged. This v2 result is a distinct negative diagnostic input and must not be retried without a new evidence-backed geometry/normal coverage repair and a new root review.

Full machine-readable report: `campaigns/core-v1/cfd/f3-baffle-exchange-source-scope-v1/runtime-canary-report-normals-v2.json` (SHA-256 `51e4855330f022e172a33118a95f6ecce05c3a5b913e06b2cbe2d88dbb34033e`).
