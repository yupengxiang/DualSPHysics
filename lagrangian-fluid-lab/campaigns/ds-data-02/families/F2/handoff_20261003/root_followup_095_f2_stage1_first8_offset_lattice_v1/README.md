# F2 fresh095 first-eight offset lattice source handoff

This package adds exactly five prospective F2 physical conditions to the three
distinct reviewed bindings already in scope:

- mother support: 327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef
- accepted P01: c994d0a680c84cdedb984d98c7fcb28bc62d2719999889d3164e44820ccb883c
- P03 native-complete, recovery-bound and still visual-pending: 402f576739ee7618ff00e5f570ba726d60a7a88017e456f6ad0aa57b46a2cab2

The five new receiver low-x values are 0.47, 0.50, 0.55, 0.60, and 0.63 m.
Each is an integer multiple of the reviewed dp=0.01 m lattice and lies
strictly between the reviewed 0.45 m and 0.65 m endpoint values. The source
definitions inherit the reviewed P01 open-rim source, fluid source, forcing
bytes, controls, TimeMax=4, TimeOut=.01, and 3-D contract. The stripped
source diff records one physical XML change: receiver low-x.

Each case has an official GenCase definition, copied native motion bytes,
source metadata, a disabled Root142 GenCase request, a disabled PartVTK-based
initial QA request, a disabled Root230 full 4 s/401-frame native request, and
an owner binding. Actual particle counts, masses, XML/BI4/report hashes, QA
results, native receipts, and visual status remain null. No count is borrowed
from the mother or endpoints.

P07 remains pre_registered_no_native_output; this handoff neither marks it
completed nor rejected. The package does not update shared registry, ledger,
scope, or production qualification.

Static checks:

- python3 -B -c 'import ast,pathlib; [ast.parse(p.read_text(), filename=str(p)) for p in [pathlib.Path("build_f2_first8_remaining.py"), *pathlib.Path("workers").glob("*.py")]]'
- python3 workers/f2_first8_source_contract_validator.py --manifest F2_STAGE1_FIRST8_REMAINING_OFFSET_LATTICE_MANIFEST.json

Running build_f2_first8_remaining.py only materializes source and disabled
metadata; it does not invoke any numerical executable or read science arrays.
