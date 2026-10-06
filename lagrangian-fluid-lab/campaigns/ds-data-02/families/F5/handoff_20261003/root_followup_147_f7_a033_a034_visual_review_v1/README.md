# F5 fresh147: F7 A033/A034 bounded visual-review handoff

This F5-owned package records a source-only, read-only review of two actual F7 original-integer-angle pipelines. It starts no job, reads or hashes no BI4/H5/CSV/DAT/VTK science payload, changes no shared state, and grants no case credit.

## Current de-duplication

Selection uses the current checkpoint 114 accepted-decision list, loaded one JSON at a time, and the already-integrated fresh146 handoff. The Root792 file is used only as the immutable first24 index; its stale `already_accepted` field is not used to decide eligibility. A031 is accepted in checkpoint114, and A032 is excluded by the prior fresh146 selected pair. All first24 P5 rows are explicitly excluded by the current accepted decisions. The earliest remaining complete original-integer rows are:

- `F7_OBSTACLE_QUINTIC_B08_A033`, first24 rank 6, actual converter scope `16be75f99b3df718625d66456f4221dd5a7a9853a0419ad23610a1b8c4f824f1`.
- `F7_OBSTACLE_QUINTIC_B08_A034`, first24 rank 8, actual converter scope `f66dec975fd65c3ba4b4d75b367de11b48b537d0f09cad9e5332fa8998c51681`.

For both rows, checkpoint114 has no accepted decision with the same case ID, condition hash, or pair, and fresh146 has no matching ID or converter hash. No new execution or independent-case increment is claimed.

## Actual producer chain and visual review

Each case has an actual completed/0 GenCase, native 601-frame solve, initial QA, typed NVMe conversion, N3 XMF, and 601-frame render. Producer metadata records 3-D counts of 70,179 total: 27,495 fixed, 1,984 moving, 0 floating, and 40,700 fluid. The physical window is 0–12 s with 601 saved states at 0.02 s. Native motion is the actual sampled piecewise-linear trajectory, not C2.

Every one of the 26 contact sheets and the ten keyframes 0, 14, 125, 200, 300, 400, 450, 500, 550, and 600 was reviewed for each case. Both render sets show coherent tank/obstacle evolution with local deformation and wake. Sparse isolated blue points appear early outside the nominal tank envelope and are disclosed for Root review. No broad explosive dispersion, broad wall escape, or premature termination was seen in this bounded screen. This does not establish particle-level containment, numerical precision, or physics acceptance; Root adoption remains required.

## Scope and historical digest erratum

The immutable owner JSON retains a historical 63-character `source.source_plan_sha256` ending in `...a185`. The actual SHA256 of `first24-plan.json` is the separate 64-character value `62442d284f2c7c011030c0c4e7c1756f7e0209d0be7cbf11a125d36e836a1855`; fresh147 records both and never claims equality.

For A033, the source-declared condition is `85871dcba0b3641b528430df2953f46da55825638aa888680bb215b944866199`; for A034 it is `74bc214a37db83c467d74ee9f4dab85b439333edfb577100ca77fc64368ebe18`. These remain separate from the actual converter/canonical scopes above, the owner/source-definition hashes, and the producer legacy scope. No cross-resolution or C2 equivalence is inferred. The historical DP-lattice precision negative evidence remains separate; Q-N, production approval, and case credit remain ungranted.

## Validation

```bash
python3 -B scripts/validate_fresh147.py
```

The manifest excludes its own `manifest.json` and the generated validator report, so listed package hashes are stable.
