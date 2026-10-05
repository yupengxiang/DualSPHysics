# F1 fresh091 actual GenCase to initial-QA binder

This package binds the 24 Root438/439 fresh090 GenCase attempts after metadata-only verification. Every receipt is `completed` with return code 0, generated XML is parsed and content-hashed, and generated counts/3D/dp are checked against the producer report. The derived GenCase binding adds the missing `dp_m` required by `root_native_source_preflight_tools_001/gencase.py`; it is a rebindable contract and does not edit fresh090 or request a rerun.

The 24 initial-QA requests are disabled and Root-owned. They invoke the existing official PartVTK QA worker only after Root enables them. `fluid_mk=1` is retained as the actual native QA contract; the XML `mkfluid` declaration and GenCase raw velocity are not treated as saved solver frame-0 proof. Future native/QA receipts and reports remain null.

The input audit recomputes hashes for non-science files and records the actual runner path aliases. BI4 exists and its SHA is recorded only from `prepared-input-report.json`; this source agent did not open or hash BI4, H5, CSV, DAT, VTK, or any array payload.

`metadata/first24-plus-new24-union.json` proves 48 unique source tuples by mechanism, continuous fluid depth, and initial velocity. Retry, resolution, time-window, and source-label aliases do not count. No Q-N or visual/production approval is granted.

Root may inspect and enable a request with the strict runner after reviewing the disabled contract.
