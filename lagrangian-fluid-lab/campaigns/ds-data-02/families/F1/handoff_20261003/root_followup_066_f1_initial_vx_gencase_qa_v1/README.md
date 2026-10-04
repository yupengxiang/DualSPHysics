# F1 fresh066 initial-vx GenCase and QA source handoff

This source-only handoff binds the existing first-eight F1 head conditions to
one additional physical axis: uniform initial fluid velocity `vx=0.1` and
`0.2 m/s`, with `vy=vz=0`.  It contains 16 independent prospective cases,
one pair of velocities for each of the eight parent conditions:

```text
ECC H110, H130, H150 fallback, H190
DUAL H220, H260, H300 fallback, H340
```

The parent geometry, DP, fluid source, and continuum metadata remain bound to
the fresh064 source.  The only XML control change is the official direct
`<initials><velocity mkfluid="0" x="..." y="0" z="0" /></initials>`
element.  The first-eight audit is metadata-only: its positive 3D particle
counts and positive source mass are references for the new bindings.  It does
not open BI4/H5/CSV arrays and does not claim the new cases were generated.

Each case has a disabled genuine GenCase request and a disabled read-only
vx-aware initial-QA request.  The QA worker must verify the generated output's
positive 3D fluid population, positive mass/density, and the actual fluid
velocity `(vx, 0, 0)`; no zero-velocity QA result is reused.  This handoff
deliberately contains no native solver request.  Root must run GenCase first,
then the QA worker, and review the resulting receipts before any later native
visual request or acceptance decision.

All future output, receipt, and QA digests remain `null`; `launch_allowed` and
`execution_allowed` remain `false`.  The handoff increments the Stage1 case
count by zero and does not modify shared registry or ledger state.

Static validation, which reads only source JSON/XML and hashes small request
inputs, is reproducible with:

```bash
python3 bind_f1_first8_vx_gencase_qa.py --output metadata/static-validation.json
python3 -m unittest discover -s tests -v
```
