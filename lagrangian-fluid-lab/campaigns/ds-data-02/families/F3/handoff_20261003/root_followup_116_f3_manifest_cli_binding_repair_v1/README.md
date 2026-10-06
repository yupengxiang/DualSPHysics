# fresh116 Root023 manifest CLI binding repair

fresh116 is a narrow F3-scoped successor of fresh114. It preserves the
bounded failure logging and publication lifecycle from fresh114 and fixes one
metadata binding defect found by the registered Root945 diagnostic: the
renderer command must receive the absolute manifest JSON path, while the
parsed manifest object is used only for frame/particle checks.

The old implementation returned `str(parsed_manifest)` from
`_manifest_metadata()`. Root023 therefore received a Python dictionary
representation as the `--manifest` argument. Root945 measured a 49,002-byte
argument and the first registered request failed before any product was
published. fresh116 keeps `manifest_path` separate and passes the original
absolute path. The regression test observes the exact `Popen` argv and rejects
the dict representation.

The package is source-only. It does not alter fresh112, fresh114, Root934, or
Root945, and it contains no enabled production request. Its tests use toy JSON,
XMF metadata, and fake subprocesses only; they do not open or hash H5, BI4,
CSV, DAT, VTK, or other scientific payloads and do not launch ParaView.

Validation:

```text
python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 scripts/validate_fresh116.py
```
