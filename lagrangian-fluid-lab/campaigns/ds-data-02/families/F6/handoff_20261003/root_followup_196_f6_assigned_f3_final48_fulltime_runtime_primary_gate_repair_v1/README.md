# fresh196 F3 full time primary gate repair

This is an F6-owned, source-only handoff for the eventual F3 final48 primary delivery. It is a new package and leaves fresh195 (`e88e7c6e6574a54d87c311e59b8baec8094f7864`) byte-for-byte unchanged. It does not start jobs, read or hash H5/BI4/IBI4/CSV/DAT/VTK payloads, write shared state, award case credit, or assert numerical precision.

The builder consumes explicit metadata inputs and always writes into a newly named output directory. At the frozen assignment inputs (`ROOT_LIVE_RESUMPTION_CHECKPOINT_291.json`, Root1389 current index) the observed boundary is 48 registered F3 rows, 44 authoritative accepted decisions, and 4 pending rows. The checked result is therefore `fresh196-readiness.json`; a `F3-FINAL48-COMPLETE-PRIMARY-DELIVERY.json` is forbidden until all 48 rows have their own accepted decision and every primary gate passes.

The authoritative membership is read from Root1276 in its stored order. The validator enforces frozen8 ⊂ actual24 ⊂ registered48, exact decision path/SHA membership in the checkpoint, family/case/physical identity, and accepted status. It does not reinterpret a directory, alias, count, or historical catalog as membership.

For each accepted row, completion requires genuine producer evidence. Execution receipts must use `ds02.execution-receipt.v1`, terminal `completed`, integer `returncode=0`, matching case/physical binding, request input-file/hash closure, launch and post-run digest snapshots, worktree/cwd, and output-root provenance. A runner request, a status string, or a separate QI summary cannot stand in for a receipt. The validator also retains the original running/no-returncode native or typed attempts and any recovery evidence instead of rewriting them to success.

The full time gate joins the actual render report, XMF manifest, XML/XMF, typed conversion report, native receipt, genuine initial-QA receipt plus pass report, and GenCase provenance. It verifies 836 frame diagnostics, strict producer times, 179208 particles, N3 geometry/velocity metadata, finite active fields, active-plus-missing accounting, type ledgers, and the typed `(Zone,Idp)` identity. Typed metadata must include an initial-exclusion ledger, explicitly rejected/closed introduced IDs, per-frame type/active/missing data, PartVTK pass, 3D solver metadata, and source provenance. A QA receipt without a real QA report is rejected. An invalid identity key or absent exclusion ledger is rejected.

Native canonical, typed legacy, XMF condition/physical plan, source plan, SourceDef, accepted top hash, and actual converter scope remain separate role and presence masks. Root1348’s source209 correction, Root1330 request-to-receipt corrections, source177 date-only review, source178 actual review time, and AY0270’s own-QI SHA `d580c83cf9ab4ca5e2fd5f09ac3a9f73adfd90dab70115dad035cb1d7ecbde91` are preserved with their roles. AY0270 own QI is not promoted to initial QA or visual acceptance.

Run the source boundary with the fixed assignment snapshot:

```sh
python3 scripts/build_fresh196.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_291.json \
  --current-index /abs/path/full336-current317-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F3-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json \
  --output-dir /abs/path/new/fresh196-output
```

Validate the same metadata without writing into this package:

```sh
python3 scripts/validate_fresh196.py \
  --checkpoint /abs/path/ROOT_LIVE_RESUMPTION_CHECKPOINT_291.json \
  --current-index /abs/path/full336-current317-actual-final48-delivery-progress-index.json \
  --membership /abs/path/F3-ACTUAL_FIRST24_DYNAMIC_DELIVERY.json \
  --legacy-catalog /abs/path/F3-FINAL48-ACTUAL39ACCEPTED-NINEPENDING-PRIMARY-DELIVERY.json
```

The validator runs synthetic negative checks for runner-request masquerading, missing 836-frame ledgers, wrong/incomplete times, incomplete XMF, QA receipt without report, invalid typed identity, missing initial exclusion, and nonempty output overwrite. At the frozen input snapshot it passes those checks and reports 35 accepted rows with evidence gaps plus the 4 pending decisions. Those gaps are readiness facts, not failures of the underlying simulations and not visual or numerical certification.

The same validator was also exercised with the later explicit checkpoint/index pair (cp297/current319): it derived 45 accepted and 3 pending rows without source changes. It has no fixed 44/4 or F2-specific correction gate; Root1330 corrections are only retained when the supplied F3 row actually carries that provenance.

All source timestamps are generated at execution time; no timestamp is rounded or used as scientific evidence. `Q_N=0`, `Q_E=0`, `new_case_credit=0`, and `scientific_payload_read_or_hashed_by_source=false`.
