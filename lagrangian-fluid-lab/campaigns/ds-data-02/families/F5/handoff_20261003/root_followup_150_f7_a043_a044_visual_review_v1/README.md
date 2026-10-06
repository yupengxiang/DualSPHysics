# F5 fresh150: F7 A043/A044 bounded visual-review handoff

This F5-owned package records a source-only, read-only review of the two explicitly assigned original-integer F7 frontier rows A043 and A044. It starts no job, reads or hashes no BI4/H5/CSV/DAT/VTK science payload, changes no shared state, and grants no case credit.

## Target selection and de-duplication

The immutable Root792 frontier is the full actual F7 pipeline index. A043 is frontier rank 26 and A044 is rank 28. They were selected explicitly from Root792 after checking the checkpoint 114 accepted-decision JSONs and the prior F5 handoffs fresh146, fresh147, fresh148, and fresh149. A040 is already accepted in checkpoint 114; A041/A042 remain assigned to the production recovery workstream and are not silently claimed by this package. All Root792 P5 rows are excluded by rule. Prior A031/A032, A033/A034, A036/A037, and A038/A039 are excluded by their immutable F5 handoffs. Root792's `already_accepted` flags are recorded as provenance and are not used to grant credit.

Both selected rows have actual completed/0 GenCase, native full 601-frame solve, initial QA, typed NVMe conversion, N3 XMF, and 601-frame render metadata. Producer metadata reports 3-D counts of 70,179 total: 27,495 fixed, 1,984 moving, 0 floating, and 40,700 fluid. The physical window is 0–12 s with 601 saved states at 0.02 s. Native motion is the actual sampled piecewise-linear trajectory, not C2.

## Visual review

For each case I reviewed all 26 contact sheets and ten event keyframes (0, 14, 125, 200, 300, 400, 450, 500, 550, and 600). Both render sets show coherent tank/obstacle evolution with local deformation and wake. Sparse isolated blue points appear early outside the nominal tank envelope; this is recorded as the same bounded, nonblocking visual limitation disclosed in the preceding F7 handoffs. I saw no broad explosive dispersion, broad wall escape, or premature termination. This is a visual screen only: it does not establish particle-level containment, numerical precision, physical acceptance, Q-N, production approval, or case credit. Root adoption remains required.

The actual converter/canonical scopes are:

- A043: `60ad2b0a66bfe6516c2fc71ab971b2574d07d626294c39f39c9c66c6d5c913e0`
- A044: `171733d3faf078acbccfec473975df312a67cf00778b0898a14e5db34f3961cd`

The source-declared physical scopes remain separate from those actual converter scopes. The immutable owner JSON retains a historical 63-character `source.source_plan_sha256` ending in `...a185`; the actual SHA256 of `first24-plan.json` is the separate 64-character value `62442d284f2c7c011030c0c4e7c1756f7e0209d0be7cbf11a125d36e836a1855`. This package records both and never claims equality. A043's source-declared condition is `2f3d3ff56489f1b57bca3d8f44f3141e9fdf5753e124f228ecc3ccd7f67d7fa8`; A044's is `8315725b88225612fd093038b76f9e52838bbb63a031668bc1db6db094297a53`. No cross-resolution or C2 equivalence is inferred. Historical DP-lattice precision negative evidence remains separate.

## Validation

```bash
python3 -B scripts/validate_fresh150.py
```

The manifest excludes its own `manifest.json` and the generated validator report, so listed package hashes are stable. Future acceptance, Q-N, production approval, and case credit remain unset.
