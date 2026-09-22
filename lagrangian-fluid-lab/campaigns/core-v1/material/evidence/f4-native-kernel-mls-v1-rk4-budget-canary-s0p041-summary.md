# F4 native RK4 budget canary profile

CPU-only causal trace of the qualification-only dense source. Source SHA `eaa423cd1e6cdb2e0bd89fcd9b0332fd0e9524e10be0c907926d4155b3ce46b9`; code SHA `69229cf7126afea3ff148a91e8aaa79174f63ad03a0f1160a2323e0d1f2761b2`; trace SHA `f4854315a0413401e390ca2205ba1e7ce67298f534d296c00bacedd582badb23`. No solver/GPU/ledger and no T2 claim.

The run processed frames 0–20 (`.04000757 s`) with 512 independent equal-mass seeds, four RK4 substeps per native interval, and current-frame hold for all stages. It used 182.06 user CPU seconds, 168.73 s wall, and 158816 KiB peak RSS. Mass closure was exact and numerical unknown fraction was 0.0, but this is only a support mask: material reliability remains unassessed, the real-source analytic upper bound is unavailable, and the event window is right-censored before contact.

The p95 weighted reconstruction residual was `0.000376948805 m/s`; the p95 cumulative RK-vs-Euler path estimate was `1.593864533451458e-6 m`. These are diagnostic estimates, not certified material error bounds.
