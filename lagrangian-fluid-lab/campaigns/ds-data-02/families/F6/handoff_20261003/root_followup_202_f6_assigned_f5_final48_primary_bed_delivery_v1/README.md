# F5 fresh202 final48 primary/bed delivery metadata

This source-only package records the F5 roster at cp320: 44 accepted physical cases and four still-registered pending cases. It combines the 30 accepted Root1344 primary/bed rows with the 14 accepted rows added by the Root1432 index. The explicit Root1293 membership arrays are carried verbatim through Root1344; frozen8, actual24, and registered48 are independent of the current accepted count.

The four legacy atomic publish receipt absences (A080, A120, M085/T080, M115/T100) remain null. A080/A120 have a separate XMF506/bed508 execution-zero preflight reference; it does not manufacture a render publish receipt. Pending future render, termination, and publish hashes remain null; only M110/T100 has the parent dispatch live-worker observation (PID 769309, start_ticks 215244107), and that observation is not a terminal result.

The product JSON preserves native canonical, typed legacy, XMF physical-plan, SourceDef XML, source-plan JSON, genuine GenCase, initial-QA, full801 UID/N3/time/finite, bed diagnostic, render receipt/report, and PNG role metadata separately. PNGs are only stat'ed and producer-declared hashes are retained; no PNG or scientific payload was read or hashed. Precision, strict-containment, and sub-DP claims remain unaccepted.

The JSON also carries post-assembly dispatch observations for the four pending cases. These observations are outside the frozen cp320 acceptance snapshot: two workers were later observed running, M110/T100 was observed completed and atomically published but remains unaccepted under production recovery fresh192, and all receipt/publish hashes remain null in this package.

Run the read-only validator from this package:

```sh
python3 scripts/validate_fresh202.py --package .
```

The assembly utility accepts `--checkpoint`, `--current-index`, `--legacy-catalog`, and an empty `--output-dir`; it refuses to overwrite a non-empty output directory.
