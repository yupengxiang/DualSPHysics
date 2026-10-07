# Fresh195 F4/F5 actual native-pinned tuple audit

This compact source package audits the 96 F4/F5 rows from fresh194. Each row
selects one JSON file from that case's actual native request `input_files`.
The selected file is case-bound, is present in the request, and has equal
launch and after-run metadata hashes. The report reads the numeric fields from
that selected JSON and records their JSON pointers, the native receipt, and
the request input hash. Owner-only or future-only claims are excluded.

The only normalized fields are:

* F4: `gap_m`, `x_offset_m`, `y_offset_m`, `speed_m_per_s`.
* F5: `amplitude_scale`, `time_scale`.

Every pair within each family has a difference in at least one shared known
field. Unknown values never count as a difference. A080 and A120 have a
native-pinned amplitude (`0.8` and `1.2`) but no pinned `time_scale` field;
that missing time is retained and their known amplitudes differ from every
other F5 row. Native condition, typed legacy scope, and original field
absences remain separate metadata roles and are not filled from aliases.

The validator reopens only JSON metadata. It checks the native receipt is
completed with return code zero, the selected path is an exact request input,
the JSON bytes match the launch and after hashes, the recorded pointers still
contain the recorded numbers, and the pairwise shared-known-field proof has
no failures:

```text
python3 -B /home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_195_f3_assigned_f4_f5_actual96_native_pinned_physical_tuples_v1/scripts/validate_actual96_native_pinned.py
```

The audit is source-only. It did not read, hash, or copy BI4, H5, CSV, DAT,
VTK, or PNG payloads; start jobs; modify shared state; or grant case, Q-N, or
Q-E credit. The earlier rich fresh194 tuple report remains separate and is
not used as owner-only authority here.
