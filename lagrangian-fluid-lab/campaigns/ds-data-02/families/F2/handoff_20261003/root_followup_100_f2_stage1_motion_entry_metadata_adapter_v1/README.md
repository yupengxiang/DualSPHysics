# F2 fresh100 motion-entry and metadata adapter

This source-only package adapts every fresh099 case to a Root-owned
motion-safe GenCase entry. fresh099 remains untouched. Each binding stages
the XML and its exact .dat motion asset in the fresh attempt directory, runs
the official GenCase there, verifies/restores the staged asset, and emits the
actual XML/BI4 digests and prepared-input-report.json. No count, mass, QA,
native, typed, visual, Q-N, or production evidence is filled here.

The initial-QA command first reads the actual prepared-input-report JSON and
matching GenCase receipt with f2_prepared_report_contract_audit.py, then
invokes the existing bounded F2 PartVTK initial-QA worker. Output and all
scientific hashes remain null in these disabled requests.

The owner adapter intentionally omits physical_binding.v1. The exact direct
converter fallback is therefore prospective legacy-owner-scope.v0. The
source-plan hash, prospective legacy hash, and future actual converter hash
remain separate. Canonical physical binding and qualification/production
approval remain absent.

Root chain: enable one gencase request; review its actual receipt and
prepared-input-report; enable matching initial QA; review it; then use the
exact native 4 s, .01 s, 401-frame request. NVMe conversion remains disabled
until those actual receipts exist. No GenCase, PartVTK, solver, converter,
decoder, array reader, shared ledger, or shared registry was run or modified
by this package.
