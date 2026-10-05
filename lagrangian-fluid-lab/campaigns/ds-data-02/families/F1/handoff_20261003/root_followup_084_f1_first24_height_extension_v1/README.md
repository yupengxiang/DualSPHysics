# F1 fresh084 first24 height extension (source-only)

The authoritative checkpoint reports F1 accepted=13. The source/native registry audit in this package finds 8 existing mother tuples and 8 completed VX tuples, for 16 distinct source/native conditions. The eight fresh084 rows are the minimum prospective source set needed to reach a planned first24. No row receives a case-count increment, visual acceptance, Q-N, precision, or production approval here.

ECC uses legal dp=.01 fluid drawbox z values .11/.13/.15/.17 (nominal depths .12/.14/.16/.18), with 161 saved states over 1.6 s. DUAL uses legal dp=.02 z values .22/.26/.30 (nominal depths .24/.28/.32), with 401 saved states over 4.0 s. The eighth DUAL row is a distinct VX=.10 initial state at the legal H=.24/z=.22 grid; its frame-0 velocity requires future solver-saved PartVTK evidence. All other control and solver fields are frozen.

Each materialized Definition XML changes one selected fluid drawbox size/z attribute. Canonical physical-binding hashes and source-plan hashes are separate. Counts, native mass, and all generated/solver/QA digests remain unknown/null until Root enables the disabled requests.

Root review order is GenCase, actual native frame-0 QA, then full-native qualification through the strict Root146 entry. Qualification requests carry the Root230 eight-UUID lease profile, CPU4, 8192 MiB peak GPU, 16 GiB storage and 14400 s wall cap. Forcing, MDBC, motion and CPU solver options are forbidden.

First two disabled GenCase request paths:
- /home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_084_f1_first24_height_extension_v1/requests/F1_STAGE1_ECC_H120_DP010.gencase.request.json
- /home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_084_f1_first24_height_extension_v1/requests/F1_STAGE1_ECC_H140_DP010.gencase.request.json

Run the bounded source check without enabling a request:
PYTHONDONTWRITEBYTECODE=1 python3 /home/jade/.codex/worktrees/ds-data-02-f1/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/handoff_20261003/root_followup_084_f1_first24_height_extension_v1/validate_source_contract.py

This package did not run GenCase, solver, PartVTK, conversion, rendering, or any job. It did not read or hash BI4/H5/CSV scientific arrays and did not modify shared registry or ledger.
