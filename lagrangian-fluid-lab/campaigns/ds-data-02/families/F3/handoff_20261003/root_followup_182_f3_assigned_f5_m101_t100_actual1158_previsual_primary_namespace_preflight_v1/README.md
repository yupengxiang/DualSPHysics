# fresh182: F5 M101/T100 previsual namespace preflight

This is an F3-assigned, F5-actual metadata handoff for
`F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M101_T100_NEXT34` /
`F5_COMPACT_RUNUP_RECOVERY_C082S1_M101_T100`.

The preflight closes the real GenCase, initial-placement QA, native, typed,
XMF, and bed producer metadata.  It records the actual 3-D identity
(`194427 = 158559 fixed + 31658 fluid + 4210 moving + 0 floating`), 801-frame
metadata contract, source-definition and source-plan roles, and the separate
canonical native and legacy typed scopes.  Native/XMF condition fields that
are absent or explicitly null remain so; a physical-condition digest is not
backfilled into a missing condition field.  The bed `SourceDef.xml` role is
kept separate from the XMF physical role, and the XMF historical legacy scope
is retained as historical context only.

The current original1158 render is observed from its real receipt and process
metadata.  At build time it is a live `running` receipt with no return code,
no published report, and no private PNG output.  The package treats this as a
pending previsual state.  If the receipt changes later, the validator accepts
only a valid current `running`, `completed/0`, or explicitly failed/cancelled
state; no state grants visual credit.  A completed render still requires a
separate personal visual review.

The builder and validator read/hash only JSON/XML/XMF/Python/Markdown.  H5,
BI4, IBI4, CSV, DAT, VTK, and other scientific payloads are represented only
by producer-attested metadata values.  The package gives no Q-N, Q-E,
precision, production, or case credit.

Run the read-only validator from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 validate_fresh182.py
```

To refresh the observed metadata snapshot in a new output directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 build_fresh182.py --output-dir /path/to/new-package
```

The package manifest excludes its own hash to avoid a self-reference cycle.
