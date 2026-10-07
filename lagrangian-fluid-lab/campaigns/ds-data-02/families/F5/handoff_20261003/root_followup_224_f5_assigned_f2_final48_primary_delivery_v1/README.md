# Fresh224 F2 final48 primary-delivery handoff

This is a metadata-only F5 handoff for the F2 final48 roster. It records 47
actual primary products and the one remaining primary-delivery boundary,
`F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX053_RY014_FILL080_ROT090` (original
1063). This package is frozen at the Root320/Root1429 source boundary: its
pending record preserves the then-live, not-completed observation. The later
1063 completed/0 and own-QI transition is intentionally handled by the
separate fresh225 personal-review package and is not promoted or counted here.
Running is kept separate from completed/0 in this frozen package.

The membership arrays are copied from the Root1330 delivery sidecar and retain
the Root1276 relation `frozen8 ⊂ actual24 ⊂ final48`. Product order follows
that explicit final48 array. The 42 inherited products are kept as the actual
Root1330 primary sidecar rows. The five current additions are bound to their
own decision, QI, native/typed/XMF, GenCase, initial-QA, render, report, and
publish metadata:

- RX049/ROT075, original 1009, own QI 1392;
- RX056/ROT090, original 1097, own QI 1385;
- RX061/ROT090, original 1119, own QI 1425;
- RX063/ROT090, original 1143, own QI 1366;
- RX063/ROT105, original 1155, own QI 1346.

Each accepted product has a case-local physical condition and converter scope.
Native canonical, typed/XMF legacy, source-plan, SourceDef, and missing plan
fields remain separate. A missing key is represented as absent or null from
the producer metadata; the package does not infer it from a different role.
The new cases retain 17 contact sheets and nine published keyframe references
with producer-attested PNG bytes/digests. The personal-review references and
published-navigation references remain separate roles. The builder did not
read or hash PNGs.

The 47 rows preserve actual lifecycle omission facts, including first frame,
cumulative count, max/final count, producer-attested samples, and unknown
location/state/cause where present. No omission is filled synthetically. The
418104 and inherited 421566 particle-axis baselines remain case-local and are
not normalized. Initial-QA/GenCase claims appear only where an explicit
producer reference is present. Bed zero bins, precision results, strict
containment, sub-DP depth, and large-runup claims remain diagnostic or
unclaimed as stated by the upstream evidence.

`case_credit`, `Q_N`, and `Q_E` are zero in this handoff. It starts no job,
changes no checkpoint or ledger, and performs no scientific-payload IO. The
validator checks counts, membership, role separation, producer-reference
shape, PNG metadata cardinality, pending identity, and package file hashes.

Run the read-only validator from this directory:

```text
python3 scripts/validate_fresh224.py
```

The package manifest excludes its own self-hash; every other package file is
covered by the manifest and checked by the validator.
