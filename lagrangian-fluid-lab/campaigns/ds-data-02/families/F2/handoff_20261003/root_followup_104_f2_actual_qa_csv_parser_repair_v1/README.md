# F2 fresh104 actual QA parser repair and downstream adapter

Fresh104 binds the sixteen Root378 semantic-adapter-103 requests by their
exact attempt IDs:

`root-stage1-f2-{case.lower()}-prepared-report-qa-semantic-adapter-103`

The four reports that Root379 actually produced are retained as failed
evidence.  Each has PartVTK `returncode=0`, a CSV, and an immutable runner
receipt with `returncode=2`; the report counted 418106 rows and reported
missing `Type`, `Mk`, and `Idp`.  The other twelve cases have no actual QA
report in this source snapshot and remain pending.  No QA pass is claimed.

`workers/fresh104_initial_qa_csv_parser.py` is the Root-enabled repair.  It
scans past the PartVTK preface to the typed header, chooses the semicolon
delimiter, skips the one units row, and streams finite/type/Mk/Idp/count/mass
checks without storing particle arrays.  It accepts a Root-registered
existing CSV for the four observed outputs or invokes official PartVTK for a
pending case.  Source preparation never reads or hashes any CSV, BI4, DAT,
VTK, H5, XMF, or solver output.

The package contains sixteen disabled parser-repair QA requests, sixteen
disabled Root230 native 4 s / 0.01 s / 401-frame requests, and sixteen
disabled direct-convert/NVMe typed requests.  Native requests use the flat
prepared prefix and preserve the exact solver command (`-tmax:4.0`,
`-tout:0.01`, with no added options).  Typed requests retain the
source-plan, prospective legacy-owner, actual-converter, and canonical scopes
separately; actual converter and canonical hashes remain null.

Run the metadata-only validator with:

```text
python3 workers/fresh104_source_contract_validator.py
```

The current validation result is `pass`: 16 cases, 4 observed failures, 12
pending reports, zero observed passes, all 48 requests disabled, and no
scientific payloads read or hashed by the source builder.
