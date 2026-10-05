# F4 fresh084: Root200 full-native qualification binder

This source-only package binds the eight Root195 per-case GenCase outputs to
disabled Root200 full-native qualification requests. Each request uses its
own genuine `gencase-receipt.json` with individual subprocess return code 0,
actual 3-D counts, and producer-declared BI4/XML hashes. The Root195
aggregate `execution-receipt.json` remains a preserved `failed` wrapper with
return code 0 and error `GenCase actual particle count missing`; it is never
promoted to the GenCase authority.

Root200 remains disabled until the Root212 CPU native initial-QA producer
supplies a completed0 `initial-native-qa-index.json`, the matching
`initial-native-qa-binding.json`, and eight passing per-case reports. Root196
failed on the adopted source binding, Root210 failed before array access on
an aggregate producer path mismatch, and Root211 failed before usable QA
because the BI4 did not expose raw `Mk` and `Type` arrays. All three failed
receipts and stdout hashes remain historical evidence and are never accepted
as QA by themselves. Root212 instead uses the successful XML/UID-derived
partition with raw `Posd` and `Idp` observation; it explicitly leaves `Mk`
and `Type` unobserved.

The solver recipe is unchanged: `-tmax:1.2 -tout:0.001`, 1,201 saved frames,
DBC, and no forcing/no extra MDBC option. The binder does not read, hash,
copy, or decode BI4 arrays; it does not run GenCase, a solver, or a converter,
reserve a GPU, or write shared state.

Use `workers/build_f4_root200_native_qualification_bindings_v1.py` from the
Root-owned workflow. With no QA arguments it produces disabled source requests
using the future Root212 paths. After Root212 is actually completed0/pass,
Root may provide `--qa-index`, `--qa-binding`, and `--qa-receipt`; the builder
then verifies those small reports and records their actual hashes while
keeping every solver request disabled for explicit Root enablement.

Static check:

```text
python3 tests/test_fresh084_contract.py
```

The package makes no qualification, visual, precision, Q-N, or production
claim and increments the independent case count by zero.
