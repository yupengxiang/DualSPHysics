# F5 fresh148: F7 A036/A037 bounded visual-review handoff

This F5-owned package records a source-only, read-only review of the two earliest eligible original-integer first24 rows, A036 and A037. It starts no job, reads or hashes no BI4/H5/CSV/DAT/VTK science payload, changes no shared state, and grants no case credit.

## Selection and de-duplication

Selection is controlled by the current `ROOT_LIVE_RESUMPTION_CHECKPOINT_114.json` accepted-decision list, loaded one JSON at a time. The Root792 file is used only as the immutable first24 index; its stale `already_accepted` field is recorded but does not decide eligibility. The combined current exclusions from fresh146 and fresh147 are A031/A032/A033/A034. A035 is already accepted by checkpoint114. All first24 P5 rows are explicitly excluded by checkpoint114. The earliest remaining complete original-integer rows are:

- `F7_OBSTACLE_QUINTIC_B08_A036`, first24 zero-based rank 12, actual converter/canonical scope `1561bded2ba30766d50b35c2b1717faa3bf617e7f47b5e062b25ed09e1df5222`.
- `F7_OBSTACLE_QUINTIC_B08_A037`, first24 zero-based rank 14, actual converter/canonical scope `5698ea6413fd6928af5d458e562dcc64a74126c1bb7a7a0d4304c7681e9b92a2`.

For both rows, checkpoint114 has no accepted decision with the same physical case ID, converter condition hash, or exact pair, and neither prior fresh146 nor fresh147 selected pair matches. No new execution or independent-case increment is claimed.

## Actual producer chain and visual review

Each case has an actual completed/0 GenCase, native full 601-frame solve, initial QA, typed NVMe conversion, N3 XMF, and 601-frame render. Producer metadata records 3-D counts of 70,179 total: 27,495 fixed, 1,984 moving, 0 floating, and 40,700 fluid. The physical window is 0–12 s with 601 saved states at 0.02 s. Native motion is the actual sampled piecewise-linear trajectory, not C2.

Every one of the 26 contact sheets and the ten keyframes 0, 14, 125, 200, 300, 400, 450, 500, 550, and 600 was reviewed for each case. Both render sets show coherent tank/obstacle evolution with local deformation and wake. Sparse isolated blue points appear early outside the nominal tank envelope and are disclosed for Root review. No broad explosive dispersion, broad wall escape, or premature termination was seen in this bounded screen. The observation is a visual screen only; it does not establish particle-level containment, numerical precision, or physics acceptance. Root adoption remains required.

## Scope and historical digest erratum

The immutable owner JSON retains a historical 63-character `source.source_plan_sha256` ending in `...a185`. The actual SHA256 of `first24-plan.json` is the separate 64-character value `62442d284f2c7c011030c0c4e7c1756f7e0209d0be7cbf11a125d36e836a1855`; fresh148 records both and never claims equality. The source plan file, each owner/source-definition digest, each source-declared condition, each actual converter/canonical condition scope, and the producer legacy scope remain separate. No cross-resolution or C2 equivalence is inferred. Historical DP-lattice precision negative evidence remains separate; Q-N, production approval, and case credit remain ungranted.

## Validation

```bash
python3 -B scripts/validate_fresh148.py
```

The manifest excludes its own `manifest.json` and the generated validator report, so listed package hashes are stable.
