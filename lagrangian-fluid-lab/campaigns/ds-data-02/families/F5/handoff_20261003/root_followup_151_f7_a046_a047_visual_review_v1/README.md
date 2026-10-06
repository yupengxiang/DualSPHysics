# F5 fresh151: F7 A046/A047 bounded visual-review handoff

This F5-owned package records a source-only, read-only review of the two explicitly assigned original-integer F7 frontier rows A046 and A047. It starts no job, reads or hashes no BI4/H5/CSV/DAT/VTK science payload, changes no shared state, and grants no case credit.

## Target selection and mother reuse

The immutable Root792 file is the full actual F7 pipeline frontier. A046 is frontier rank 31 and A047 is rank 33. They were selected explicitly after checking the checkpoint 114 accepted-decision JSONs and the prior F5 handoffs fresh146, fresh147, fresh148, fresh149, and fresh150. A030–A040 are already handled by the current accepted work; A041/A042 belong to the production recovery workstream. A045 is the verified original 45-degree mother and is referenced read-only under the source plan's reuse policy; this package does not create or claim a fresh A045 case. All Root792 P5 rows are excluded by rule, and the prior selected integer pairs are excluded by their immutable handoffs.

Each selected row has actual completed/0 GenCase, native full 601-frame solve, initial QA, typed NVMe conversion, N3 XMF, and 601-frame render metadata. Producer metadata reports 3-D counts of 70,179 total: 27,495 fixed, 1,984 moving, 0 floating, and 40,700 fluid. The physical window is 0–12 s with 601 saved states at 0.02 s. Native motion is the actual sampled piecewise-linear trajectory, not C2.

## Visual review

For each case I reviewed all 26 contact sheets and ten event keyframes (0, 14, 125, 200, 300, 400, 450, 500, 550, and 600). Both render sets show coherent tank/obstacle evolution with local deformation and wake. Sparse isolated blue points appear early outside the nominal tank envelope; this remains the same bounded, nonblocking visual limitation disclosed in preceding F7 handoffs. I saw no broad explosive dispersion, broad wall escape, or premature termination. This is a visual screen only: it does not establish particle-level containment, numerical precision, physical acceptance, Q-N, production approval, or case credit. Root adoption remains required.

The actual converter/canonical scopes are:

- A046: `24173692bce7082536c85241b06980fa2046de9f2bc41c26d055ee1c2b1d835f`
- A047: `b8fe93120925d3dc8cbff653acafbccd069342a0b37dca3dadb75a4c63079dea`

The source-declared physical scopes remain separate from those actual converter scopes. The immutable owner JSON retains a historical 63-character `source.source_plan_sha256` ending in `...a185`; the actual SHA256 of `first24-plan.json` is the separate 64-character value `62442d284f2c7c011030c0c4e7c1756f7e0209d0be7cbf11a125d36e836a1855`. This package records both and never claims equality. A046's source-declared condition is `164792a7cebf6e97bce2f1701e83595efe74cc36558a29f49d1df98931978ef4`; A047's is `acff5ade6bcb8f61c27046319d60737f88319fef7f2508e829db0d0a1ceeb23d`. No cross-resolution or C2 equivalence is inferred. Historical DP-lattice precision negative evidence remains separate.

## Validation

```bash
python3 -B scripts/validate_fresh151.py
```

The manifest excludes its own `manifest.json` and the generated validator report, so listed package hashes are stable. Future acceptance, Q-N, production approval, and case credit remain unset.
