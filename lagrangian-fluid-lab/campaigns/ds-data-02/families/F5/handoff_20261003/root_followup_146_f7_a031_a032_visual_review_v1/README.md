# F5 fresh146: F7 A031/A032 bounded visual-review handoff

This F5-owned package records a source-only, read-only review of two already-produced F7 original-integer-angle pipelines. It does not start a job, read or hash BI4/H5/CSV/DAT/VTK science payloads, grant a case, or alter the shared ledger.

## Selection and de-duplication

The selected rows are the earliest complete original-integer rows in the Root792 first24 frontier that remain eligible after loading and auditing every one of the 169 JSON decisions listed by checkpoint 113. The selected pairs are:

- `F7_OBSTACLE_QUINTIC_B08_A031`, Root792 rank 2, actual converter condition `7ede03279e9c89abd3742fac009057921b89baf68765f88327831e5cb97bcd78`.
- `F7_OBSTACLE_QUINTIC_B08_A032`, Root792 rank 4, actual converter condition `d5c3896b86d548297e5583212a3d6e98bc4385658c565384e15c4fcdfa2c03a3`.

For each selected row, the checkpoint-113 audit found no accepted decision with the same physical-case ID, no accepted decision with the same actual converter condition hash, and no accepted pair. The Root792 `already_accepted` bit is retained as provenance and is not the authority. The accepted P5 rows A031P5 and A032P5 are explicitly excluded. No new execution or independent-case increment is claimed.

## Actual producer chain

Each selected case has an actual completed/0 GenCase, native 601-frame solve, initial QA, typed NVMe conversion, N3 XMF, and 601-frame render. The producer metadata records 3-D native counts of 70,179 total: 27,495 fixed, 1,984 moving, 0 floating, and 40,700 fluid. The physical window is 0–12 s with 601 saved states at 0.02 s; the native motion is the actual sampled piecewise-linear trajectory and is not represented as C2. The package keeps the historical DP lattice precision negative evidence separate, grants no Q-N, and grants no production approval or case credit.

The review covered all 26 contact sheets and the ten keyframes 0, 14, 125, 200, 300, 400, 450, 500, 550, and 600 for each case. Both views show coherent tank/obstacle evolution with local deformation and wake. Sparse isolated blue points appear early outside the nominal tank envelope; they are disclosed for Root review. No broad explosive dispersion, broad wall escape, or premature termination was seen in this bounded visual screen. This is a visual screen only: it does not establish particle-level containment, numerical precision, or physics acceptance. Root adoption remains required.

## Scope separation

The immutable owner JSON retains a historical 63-character `source.source_plan_sha256` ending in `...a185`. The actual SHA256 of the first24 plan file is the separate 64-character value ending in `...a1855`; fresh146 records both and never claims equality. The following scopes remain separate for each case:

1. the actual first24 plan-file digest `62442d284f2c7c011030c0c4e7c1756f7e0209d0be7cbf11a125d36e836a1855`;
2. the owner’s historical truncated declaration;
3. the source-declared physical condition (`a259…78501` for A031 and `f4d…e68` for A032);
4. the actual converter/canonical physical binding (`7ede…cd78` for A031 and `d5c3…03a3` for A032).

The source definition and owner hashes, canonical binding, producer legacy scope, and source-plan metadata are recorded independently. No cross-resolution or C2 equivalence is inferred.

## Validation

Run the metadata/PNG-only validator from this package:

```bash
python3 scripts/validate_fresh146.py
```

The package manifest excludes its own `manifest.json` and the generated validator report, so the listed file hashes are stable.
