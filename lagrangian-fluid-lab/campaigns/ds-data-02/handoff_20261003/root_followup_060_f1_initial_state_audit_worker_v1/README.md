# F1 fresh060 initial-state audit worker

This package contains the reviewed source implementation for the missing ECC
H130 and DUAL H260 strict CPU audit. The two requests use
`cpu_task_kind: "audit"` and remain `launch_allowed: false` until Root enables
one after source review.

`worker.py` consumes the existing genuine GenCase027 receipt, generated XML
and BI4 bindings, QA031 identity, and the official QA031 PartVTK CSV. It
streams the bound CSV and computes the actual fluid mass, native particle
weight, continuum difference, finite-state checks, and Type3/Type0 overlap
summary. It writes only the audit JSON and these five JSON sidecars:

- `initial_mass_discrepancy_report.json`
- `physics_evidence.json`
- `geometry_evidence.json`
- `motion_evidence.json`
- `no_overlap_finite_state_evidence.json`

The worker does not invoke a subprocess, solver, GenCase, PartVTK, converter,
ParaView, or GPU, and it never writes a raw particle array. Its reader
provenance is the already completed Root QA031 preflight
(`root_native_initial_state_tools_001/qa.py`) and its official CSV output. It
verifies the reader, QA receipt, PartVTK binary, GenCase receipt, XML, BI4,
prepared report, and CSV hashes before and after the audit. Mass is computed
from actual CSV `Mass [kg]` rows; no count prediction or rescaling is
substituted.

The source builder only hashes existing files and writes disabled requests:

```text
python3 build_f1_initial_state_audit_worker.py
```

Root may run a reviewed request with the shared runner after changing its
launch state under the normal parent authorization. The output audit schema
is case-specific so the existing ECC058 and DUAL059 sidecar adapters can
attach the five actual worker bindings without accepting fabricated JSON.
