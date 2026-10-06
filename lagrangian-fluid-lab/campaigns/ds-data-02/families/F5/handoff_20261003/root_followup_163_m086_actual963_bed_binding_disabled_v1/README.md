# fresh163 — M086 actual963 terminal-bound bed audit (disabled)

Fresh163 is an additive source-only successor to the adopted fresh161 CASE_ID-only adapter repair. It binds the completed Root963 M086_T085 full801/N3 XMF producer to a disabled bed-audit request. Fresh161 and all producer receipts are preserved byte-for-byte.

The actual producer chain is GenCase root848, initial placement/Mk50 QA root849, native full801 root850, typed NVMe root864, and XMF root963. The XMF producer receipt is `completed` with return code `0`, and its real metadata files are bound as follows:

- manifest JSON SHA256: `de0bba6747b8471a5dc8e8e7f9563bccd92c6e8b84a9f42a91121f651d413a36`
- `case.xmf` XML SHA256: `2354bfbed88d00bd491e41b3e17a7a6878ce1270d437a87fbb6eb2c56395aa0b`
- XMF execution receipt SHA256: `886fb86bdc13c37201f3c87ff090c29b04b7f249395e5ebacd7595325dcb957f`
- XMF attempt: `root-stage1-f5-m086-t085-actual864-full801-N3-XMF-root963`

Only the fresh161 allowlist is used for binding updates: `actual_counts`, `initial_qa_output_root`, `xmf_manifest` and its SHA, `xdmf` and its SHA, `xmf_receipt` and its SHA, and `xmf_attempt_id`. Execution, source, geometry, physics, marker, threshold, producer-count, and scope fields are unchanged from fresh161. The bed attempt/report hashes remain null. The new request stays `disabled: true`, `execution_allowed: false`, `launch: false`, `solver_allowed: false`, and `full801_authorized: false`; Root must register it through Root142.

Canonical physical scope (`89a891...`), source-plan scope (`85d0e0...`), typed legacy scope (`ff41...`), and the producer-attested H5 digest (`ee5032...`) remain separate. The source agent did not open, copy, or hash H5, BI4, CSV, DAT, or VTK payloads. The actual H5 digest is recorded only as producer metadata already present in the completed typed/XMF reports.

Root entry points:

- Binding: `bindings/M086_T085-actual963-bed-binding.json`
- Disabled request: `requests/M086_T085-actual963-bed-request.json`
- Metadata preflight: `python3 scripts/validate_fresh163.py`

The preflight verifies the real GenCase/QA/native/typed/XMF JSON/XML receipts, actual XMF metadata hashes, fresh161 immutable binding fields, exact CASE_ID adapter regression, disabled guards, and input-hash closure. It does not launch a worker or inspect scientific arrays.
