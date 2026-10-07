# Fresh194 full336 physical-distinctness role audit

This is a source-only, family-scoped audit of the 336 registered physical
cases at the frozen current-index revision. It supplies a bounded, reviewable
answer to one question: whether each family row has a case-bound normalized
physical tuple that demonstrates a physical control difference. It is a
readiness and provenance product; it grants no visual, numerical, quality, or
production credit.

The authoritative registered roster is the cp334 index recorded in
`metadata/full336-physical-distinctness-audit.json`. Its frozen membership
arrays retain each family's explicit 8/24/48 relationship. The builder uses
those arrays and the source products' case-bound membership evidence; it does
not sort IDs or use aliases, resolution, saved-frame counts, time windows,
camera/view metadata, hashes, or path strings as physical differences.

The normalized tuple is intentionally small and family-specific:

* F1: `fluid_depth_m`, `initial_fluid_velocity_m_s`,
  `fluid_reservoir_low_m`.
* F2 and F7: the pinned numeric discriminators in the independent Root1452
  native launch/after proof.
* F3: `pitch_multiplier`, `transverse_amplitude_m_s2`, using the actual
  forcing-transform/native pins from Root1456 for the two endpoint rows.
* F4: `gap_m`, `x_offset_m`, `y_offset_m`, `drop_initial_speed_m_s`.
* F5: `piston_amplitude_scale`, `piston_time_scale`.
* F6: `body_mass_kg`, `initial_angular_velocity_rad_s`,
  `initial_yaw_deg`.

All source evidence remains in each row's metadata role block. Native
canonical condition, converter/typed legacy scope, source plan, generated
XML, XMF plan, and SourceDef roles are kept separate. A missing native field
stays missing. The F1 lower-head fallback and the F6 omega-baseline XML are
case-bound repairs with explicit source files, not ID-based inference. The
F2/F7 numeric proof is
`actual96-native-pinned-physical-discriminators.json` (Root1452); the F3
endpoint proof is
`actual-two-F3-endpoint-forcing-and-stale-request-binding-proof.json`
(Root1456). Root1454's all-family fluid-omission report is included as a
lifecycle supplement only; omission counts do not establish physical
distinctness.

The audit has 336 rows and no normalized tuple collision within a family.
F5 A080 and A120 remain explicitly uncertain because their case-bound motion
or geometry controls were not available in the permitted metadata. Their one
rich metadata-signature collision is retained as a diagnostic and is not used
as a difference. The F6 omega baseline has no yaw field, which is recorded as
an explicit missing field. These facts are reflected in the summary and
validator output.

Run the read-only validator from this package with:

```text
python3 -B /home/jade/.codex/worktrees/ds-data-02-f3/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261003/root_followup_194_f3_full336_physical_distinctness_role_audit_v1/scripts/validate_physical_distinctness_audit.py
```

The optional `--verify-existing-metadata-sha` mode verifies the JSON/XML
metadata references listed by the audit. The validator refuses forbidden
scientific-payload suffixes and checks the 8/24/48 membership contract,
case-bound source resolution, normalized tuple leaves, native field-role
absences, and explicit uncertainty. It reports
`PASS_WITH_EXPLICIT_MISSING_PHYSICAL_FIELDS` for the current audit.

This package only reads JSON/XML metadata and source code. It does not read,
hash, or copy BI4, H5, IBI4, CSV, DAT, VTK, or PNG payloads; launch work;
modify shared state; or grant case/Q-N/Q-E credit. The lifecycle supplement
reports the separately verified relative fluid omissions: F1/F3/F5/F7 have
zero, F2 reaches 118, F4 reaches 6 across 22 cases, and F6 reaches 7. These
are preserved as observed diagnostics, with causes and precision limits left
open.
