# F1 fresh076: Root162 actual GenCase to disabled full-native qualification

This is the F1-isolated `root_followup_076_f1_eight_actual_gen_fullnative_qualification_v1` source handoff. It binds eight real Root162 GenCase outputs to disabled native qualification requests. Every Root162 receipt is `completed` with return code 0, with metadata-only 3-D count evidence and the generated XML/BI4 hashes recorded by Root. The BI4 bytes are deliberately not read by this handoff.

The eight cases are the ECC H110/H190 and DUAL H220/H340 parents at initial Vx 0.10 and 0.20 m/s. Their mother solver windows and save cadence remain unchanged: ECC `tmax=1.6`, `tout=.01`, 161 frames; DUAL `tmax=4.0`, `tout=.01`, 401 frames. The native request uses the exact mother argv/options, Root146 strict qualification entry, `launch_owner=root`, the reviewed eight-solver cap profile, CPU4, 14400 s, 16 GiB storage and 8192 MiB peak GPU estimate. It forbids forcing, MDBC, motion and solver CPU options.

All native and frame-0 audit requests are disabled. Future native receipt, native `Part_0000.bi4`, frame-0 report and solver output SHA values are null. The copied official PartVTK worker only becomes runnable after Root has an actual native solver receipt; it reads the solver-saved frame 0 through official PartVTK in an isolated output directory. GenCase raw particle velocity is never used as evidence for initial Vx.

Root launch entry:

```text
python3 /home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_actual_qualifications_strict_entry_146/launch.py <enabled-request.json>
```

The requests remain disabled until Root reviews and enables them. Run the bounded source check with:

```text
PYTHONDONTWRITEBYTECODE=1 python3 validate_source_contract.py --write
```

No GenCase, native solver, PartVTK, array reader, shared registry, ledger or job was run while producing this package. Q-N, precision, visual and production approval remain unassessed.
