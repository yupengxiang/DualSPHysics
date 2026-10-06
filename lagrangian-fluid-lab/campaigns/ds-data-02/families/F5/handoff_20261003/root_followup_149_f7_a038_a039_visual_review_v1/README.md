# F5 fresh149: F7 A038/A039 bounded visual-review handoff

This F5-owned package records a source-only, read-only review of the next two eligible original-integer first24 rows, A038 and A039. It starts no job, reads or hashes no BI4/H5/CSV/DAT/VTK science payload, changes no shared state, and grants no case credit.

## Selection and de-duplication

Selection is controlled by the current checkpoint 114 accepted-decision list, loaded one JSON at a time, together with the prior F5 handoffs fresh146, fresh147, and fresh148. The Root792 file is used only as the immutable first24 index; its stale `already_accepted` field is recorded but does not decide eligibility. A035 is already accepted by checkpoint114. A031/A032, A033/A034, and A036/A037 are excluded by the prior fresh146/fresh147/fresh148 selected pairs. All first24 P5 rows are explicitly excluded by checkpoint114. The next eligible complete original-integer rows are:

- `F7_OBSTACLE_QUINTIC_B08_A038`, first24 zero-based rank 16, actual converter/canonical scope `07b578a9e040a28949d75bc90b0a109fb2e90601f9f968872b886c1df636ef13`.
- `F7_OBSTACLE_QUINTIC_B08_A039`, first24 zero-based rank 18, actual converter/canonical scope `4955d4e9abdfd58296654950747d0017fb21b5d1d905b6ae35e3fe6c7e46b8cf`.

For both rows, checkpoint114 has no accepted decision with the same physical case ID, converter condition hash, or exact pair, and none of the three prior selected handoffs matches. No new execution or independent-case increment is claimed.

## Actual producer chain and visual review

Each case has an actual completed/0 GenCase, native full 601-frame solve, initial QA, typed NVMe conversion, N3 XMF, and 601-frame render. Producer metadata records 3-D counts of 70,179 total: 27,495 fixed, 1,984 moving, 0 floating, and 40,700 fluid. The physical window is 0–12 s with 601 saved states at 0.02 s. Native motion is the actual sampled piecewise-linear trajectory, not C2.

Every one of the 26 contact sheets and the ten keyframes 0, 14, 125, 200, 300, 400, 450, 500, 550, and 600 was reviewed for each case. Both render sets show coherent tank/obstacle evolution with local deformation and wake. Sparse isolated blue points appear early outside the nominal tank envelope and are disclosed for Root review. No broad explosive dispersion, broad wall escape, or premature termination was seen in this bounded screen. The observation is a visual screen only; it does not establish particle-level containment, numerical precision, or physics acceptance. Root adoption remains required.

## Scope and historical digest erratum

The immutable owner JSON retains a historical 63-character `source.source_plan_sha256` ending in `...a185`. The actual SHA256 of `first24-plan.json` is the separate 64-character value `62442d284f2c7c011030c0c4e7c1756f7e0209d0be7cbf11a125d36e836a1855`; fresh149 records both and never claims equality. For A038 the source-declared condition is `68021303f45d56526aa0f3b16124f4dee90cebe0184bd68db297bf85b5230d08`; for A039 it is `101396eac6ed792fad97a1897f8b645b68e624928a1fdcd5bf265f45cbabf7a1`. These remain separate from the actual converter/canonical scopes above, the owner/source-definition hashes, and the producer legacy scope. No cross-resolution or C2 equivalence is inferred. Historical DP-lattice precision negative evidence remains separate; Q-N, production approval, and case credit remain ungranted.

## Validation

```bash
python3 -B scripts/validate_fresh149.py
```

The manifest excludes its own `manifest.json` and the generated validator report, so listed package hashes are stable.
