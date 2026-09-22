# F4 native RK4 budget canary (0.18 s near-contact window)

This completed CPU-only trace uses the real dense `.002 s` F4 source (SHA `eaa423cd1e6cdb2e0bd89fcd9b0332fd0e9524e10be0c907926d4155b3ce46b9`) and the pre-v2 code SHA `69229cf7126afea3ff148a91e8aaa79174f63ad03a0f1160a2323e0d1f2761b2`. It processed 512 independent equal-mass seeds through frame 90 / `0.1800111222 s`, with 4 RK4 substeps per native interval and current-frame field hold for every stage. GPU, solver, ledger, and slot use were all false; the qualification claim is none.

Measured resource use was 731.43 user CPU seconds, 1.16 system seconds, 724.82 s wall, and 157536 KiB peak RSS. Mass closure was exact and numerical support unknown mass stayed 0.0%, but the support mask is not material reliability. No independent native Hessian bound exists, so the analytic upper error bound is unavailable.

The trace observed contact for 9.375% of the seed mass by the window end, with no upward/return events; the event window is `right_censored_or_unresolved`. The p95 current-frame MLS residual reached `0.1759709 m/s`; RK4-versus-Euler per-frame path estimate p95 was `1.2652e-5 m`, and cumulative path estimate p95 was `3.3862e-4 m`. These are diagnostic estimates, not certified material error bounds.

Contact timing is consistent with the corrected source semantics: `core_cfd`'s 5% mass-below-pool contact is a proxy, while this trace's continuous z=.18 segment crossings are the independent event definition.
