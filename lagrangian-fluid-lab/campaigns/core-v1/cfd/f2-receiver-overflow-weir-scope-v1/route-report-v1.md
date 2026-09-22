# F2 receiver overflow weir: root review report

**Decision:** retain `F2_receiver_overflow_weir_v1` as a fresh F2 candidate for root review only. The mechanism is a stationary upstream finite reservoir overflowing a finite internal crest into a downstream receiver basin inside a closed outer tank. The registered q parameter changes crest height, `crest_height_m = 0.20 + 0.12*q`; there is no rotating cup, prescribed duration, source impulse, suspended obstacle, wave maker, or runup gauge.

The fixed package contains a 15-row matrix: 13 spatial cells over q = 0, 0.5, 1 and held-out q = 0.25, 0.75, plus internal-time and native-output controls at q = 0.5, dp = 0.0075 m. Every row is `not_started`. The fixed failure denominator is 15; executed, passed, censored and matrix credit are all zero. `qualification_claim=none`, `qualified=false`, and `matrix_credit=0`.

The only generated input retained for review is the q = 0.5, crest = 0.26 m, dp = 0.0075 m `generated_v4` anchor. CPU GenCase returned code 0 with 245,667 boundary particles, 228,480 fluid particles, 474,147 total particles, and zero generated normals. Native BI4 metadata/decode confirmed unique IDs, finite arrays, zero initial fluid velocity, and native mass 96.39 kg against the 96.768 kg continuous source contract (relative error -0.00390625). `generated_v1–v3` are excluded for mass-gate failure and have zero credit.

No solver, GPU, queue, ledger, or registry action was executed. No runtime product, crest-crossing event, receiver-contact event, qualification result, or T1 registration exists. The remaining blockers are a root-reviewed receiver/crest runtime adapter and observer, followed by explicit approval of one protected anchor before any matrix materialization. The root-review-only job spec is frozen with submission disabled.

Primary files:

- `candidate-card-v1.json`
- `fixed-matrix-v1.json`
- `failure-denominator-v1.json`
- `lineage-clarification-v1.json`
- `cpu-native-preflight-v1.json`
- `root-review-only-job-spec-v1.json`
- `route-audit-v1.json`

The v4 binding is recorded in `cpu-native-preflight-v1.json` and the root-review spec. The anchor definition SHA256 is `dc5908b2e88d0384fc01801ce043ec389052431f80271e766b1571d9168bae21`; `gencase-v4.log` is `66f13a6a204554912038f3f70d6f4b8b710cac1d1684304cf58d7b82e56933d8`; the native `.bi4` is `5f7eb737b08009d2c8b899e128f6d75fd243d9e78131cbbc8addd73a6e720292`; native metadata is `09a38f51705160c0c6321a01351576faacae44fe655ed8491a47e0884199fc55`.
