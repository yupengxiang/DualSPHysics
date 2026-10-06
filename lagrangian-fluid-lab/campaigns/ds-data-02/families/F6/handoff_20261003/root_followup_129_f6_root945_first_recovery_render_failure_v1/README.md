# F6 fresh129 Root945 first-recovery render failure audit

This F6-only package records the first Root945 attempt for
`F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025`. The attempt is terminal
`failed` with return code `1` after 3.246504489 seconds. Root945 requested 37
cases, held 36, completed zero, and assigned zero case credit. The old Root934
same-case failure remains a separate immutable record.

No PNG, contact sheet, key frame, full-animation report, PVSM, or published
render product was produced by Root945. I therefore did not call `view_image`,
did not make a visual decision, and did not assign case credit.

Root946 classifies the failure as
`manifest_JSON_object_string_passed_as_CLI_path`. In the Root114 worker,
`_manifest_metadata()` returns `str(manifest)` at line 450, where `manifest` is
the parsed JSON object. `execute_request()` then passes that value as the
`--manifest` argument at line 833. Root945's captured argv has a 49,002-byte
dictionary representation in that argument slot instead of the immutable
manifest path. Root023 expects `--manifest` to be a `Path` and reads it as a
file, so this failure is before any full-frame output. The bounded stderr tail
does not preserve a complete exception traceback; the source contract and
Root946 stat-only classification are the retained root-cause evidence.

The upstream native, FloatingInfo state-0, typed, and N3-XMF records are
referenced as metadata evidence only. Their source owner, classified producer
scope, and source-plan scope remain separate. Particle V0 is not used as an
angular-velocity conclusion. The successful Root943 frame-0 diagnostic is
preserved as a diagnostic-only record and is not promoted to full visual
acceptance.

Validate without opening scientific payloads:

```text
python3 workers/validate_fresh129.py
```

