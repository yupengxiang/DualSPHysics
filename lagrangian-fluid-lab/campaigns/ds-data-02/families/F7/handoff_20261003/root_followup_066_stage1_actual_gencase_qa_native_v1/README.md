# F7 fresh066 actual GenCase → initial QA → native601 source handoff

This isolated F7 handoff binds the five fresh065 target-angle source cases to the actual Root116 motion preparation and Root117 per-case GenCase outputs. It is source-only and disabled: no GenCase, PartVTK, CSV export, solver, GPU, registry, ledger, or shared-index action was performed here.

Root117's aggregate `gencase-result.json` is completed with five zero-returncode endpoint rows. Its separate top-level `execution-receipt.json` is preserved as `status=failed`, `returncode=0`, `error=GenCase actual particle count missing`; that wrapper failure is recorded in `metadata/actual-gencase-native-source-binding.json` and is never used as success evidence. Each endpoint's own `gencase/<case>/execution-receipt.json` is the accepted GenCase receipt and is `completed/0`.

The binder read XML and JSON metadata and streamed SHA-256 checks for the five generated XML/BI4 files and Root116 motion files. It verified actual 3D XML, `dp=0.02`, `TimeMax=12`, `TimeOut=0.02`, and per-case total `70179` with fixed `27495`, moving `1984`, fluid `40700`. Native mass remains `325.60001628 kg`; the continuum envelope `320.1984 kg` remains a separate value and no rescale is applied. BI4 was hashed for the recorded contract; no BI4 dataset or particle array was decoded.

`workers/run_f7_first8_actual_native_initial_qa.py` is a per-case derivative of the fresh065 QA worker. It preserves the fresh065 lineage checks and adds an explicit official CSV contract: three summary rows, header at zero-based line 3, and trailing empty rows ignored. Root must enable the five CPU requests individually only after reviewing the actual binding. The five full601 native requests remain disabled until each case has an actual QA report and receipt; their future QA hashes are deliberately `null` and make no claim of completion.

The solver request keeps the exact fresh065 native recipe: `-tmax:12`, `-tout:0.02`, 601 frames, and the Root116 prepared per-case directory as `cwd`, because that is where `motion_obstacle_quintic.dat` is present. Canonical owner binding hashes and source-plan SHA are recorded as separate fields. No Q-N, precision, visual, or production approval is granted.

The generated files are:

- `metadata/actual-gencase-native-source-binding.json`: actual Root116/117 evidence and five case bindings.
- `metadata/csv-contract.json`: the explicit three-summary-line/header-line-3/trailing-empty CSV contract.
- `requests/*.native-initial-qa-request.json`: five disabled per-case CPU requests.
- `requests/*.full601-native-qualification-request.json`: five disabled native GPU requests pending actual QA.
- `workers/run_f7_first8_actual_native_initial_qa.py`: source QA worker.
- `manifest.json`: scope and immutability summary.

Fresh066 itself is committed locally on the F7 branch. Root may re-run the builder against the same actual receipts to reproduce the metadata, but must not replace the preserved top-level failure with an aggregate success claim.
