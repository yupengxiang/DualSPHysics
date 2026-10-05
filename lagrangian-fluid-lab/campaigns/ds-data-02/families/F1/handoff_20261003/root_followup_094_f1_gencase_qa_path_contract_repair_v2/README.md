# F1 fresh094 GenCase QA path-contract repair

Fresh091 remains immutable with its missing `case["prefix"]` failure. Fresh093 supplied `prefix`, and Root467 reached the real PartVTK export before failing at `ET.parse(str(Path(case["prefix"]) + ".xml"))`: a `Path` plus `str` TypeError. Fresh094 changes exactly that path construction to `ET.parse(str(case["prefix"]) + ".xml")`; the scientific checks and thresholds are unchanged.

The package contains 24 disabled retry requests and corrected bindings. It records actual GenCase JSON/XML metadata, producer-attested BI4 provenance, and 3-D/count metadata. It contains no BI4/CSV/H5/DAT/VTK payloads, runs no worker, and binds no QA receipt/report as successful. Root may enable the requests after review; any future receipt/report remains null in this source package.
