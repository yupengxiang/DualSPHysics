# F1 fresh067: VX corner native qualification source handoff

This package selects the four physical F1 corner parents from fresh066:
`ECC H110`, `ECC H190`, `DUAL H220`, and `DUAL H340`.  Each has two distinct
uniform fluid initial-Vx definitions, `0.10` and `0.20 m/s`, for eight
independent physical condition hashes.  The other eight fresh066 candidates
(`ECC H130`, ECC fallback, `DUAL H260`, and DUAL fallback at both velocities)
are recorded in `metadata/preserved-first24-candidates.json` and are untouched.

The parent sources are genuine 3-D metadata references.  Their geometry and
solver recipes remain exact: ECC uses `dp=.01`, `tmax=1.6`, `tout=.01`, 161
saved frames; DUAL uses `dp=.02`, `tmax=4.0`, `tout=.01`, 401 saved frames.
Continuum source mass and native particle weights remain separate; no mass
rescaling or equality claim is made.

The evidence boundary is explicit.  The direct XML `<initials><velocity
mkfluid="0" .../>` declaration is source evidence.  GenCase may still emit a
raw BI4 whose particle velocity is zero because solver initialization applies
the XML control at startup, so this package never treats GenCase BI4 velocity
as proof.  Root first obtains a genuine GenCase completed/0 receipt and its
3-D metadata, then runs the exact mother native command through Root146.  The
disabled CPU frame-0 audit invokes official PartVTK with
`-dirdata solver_output/data -first:0 -last:0` and checks the saved
`Part_0000.bi4` fluid Type 3/Mk 0 velocity against the requested VX, finite
positive mass/density, unique `(Zone,Idp)` and coordinates, 3-D levels, counts,
and zero frame time.  It hashes the native frame before/after PartVTK to prove
read-only use and writes an isolated CSV/report.  It does not grant Q-N,
precision, visual, production, or case-count status.

All eight GenCase, frame-0 QA, and full-native qualification requests are
`launch_allowed=false` and `execution_allowed=false`.  Native requests bind
Root146 (`kind=qualification`, `launch_owner=root`), preserve the mother
argv/options, forbid forcing/MDBC/CPU overrides, and leave every future
receipt/output digest null.  Root may create actual bound requests after the
strict checks and resource guards pass.

Run the metadata-only source check from this directory:

```text
python3 validate_source_contract.py --write
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

No GenCase, PartVTK, solver, numeric-array reader, shared registry, ledger, or
job was run while preparing this source package.
