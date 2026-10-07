# Fresh208 F3 actual forcing correction

This sibling sidecar corrects the interpretation of the fresh207 F3 spot
audit.  Fresh207 remains immutable and records the stale native-request
`physical_binding` (`AY0P50`, amplitude `0.5`) exactly as found.  Fresh208
joins each endpoint's JSON forcing producer report to the actual lower/upper
command prefix, endpoint XML, and native launch/after input-hash maps.

The producer reports attest `amplitude_y=0.25` and `0.75`, with output CSV
hashes `486511...2f9ec` and `e2d414...d7b67`; those exact output paths are
present in the native receipt launch and after maps.  The XML uses the relative
`acctimesfile` value `CaseSloshingAccData.csv`, and its resolved case-folder
path is the same producer output path.  The CSV itself is never opened or
hashed by this package.  The endpoint XML SHA is still identical between the
two cases, but that does not erase the distinct producer forcing inputs.

No numeric pitch value is present in the binding/report metadata.  `P1000` is
retained as a label only and is never converted from an identifier into a
numeric tuple value.  The corrected conclusion is therefore that actual
forcing input is endpoint-distinct, while the stale request binding remains a
separate provenance contradiction requiring explicit disclosure.

Run:

```text
python3 scripts/validate_forcing_correction.py metadata/f3-actual-forcing-correction.json
```

No case credit, Q-N/Q-E, precision, or scientific result is granted.
