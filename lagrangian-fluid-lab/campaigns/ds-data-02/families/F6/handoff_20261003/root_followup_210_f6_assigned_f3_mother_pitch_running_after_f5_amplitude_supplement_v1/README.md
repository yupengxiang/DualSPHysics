# fresh210 bounded metadata supplement

This package supplements fresh209 without changing fresh207, fresh208, or fresh209.

It closes the F3 mother case's drive-factor evidence: native060's
`actual_continuum_binding` and the source056 prepared report both carry
`drive_amplitude_G`/`forcing_transform.amplitude_x = 1.0`. The numeric pitch
field remains absent and is deliberately left null; no identifier or image is
converted into a pitch value.

The four original F3 native-059 receipts remain `running`, with no returncode
and no after-run hash map. Their request amplitude declarations are joined to
their actual prepared producer reports (`0.32`, `0.39`, `0.46`, `0.57`), and
the producer-attested forcing output SHA is compared only with the launch pin.
The after state remains unknown; no completion or after pin is synthesized.
The separate Root1449 recovery product and Root1435 typed-artifact scope are
referenced only as downstream roles; neither rewrites an original 059 receipt.

For F5, A080 and A120 are checked against the existing fresh209 F5 rows using
`amplitude_scale` alone: `0.8` and `1.2` each occur exactly once. Their
`time_scale` values remain unknown/null and are excluded from distinctness.

Run the standalone validator from this directory:

```bash
python3 scripts/validate_supplement.py
```

Only JSON/XML metadata was read or hashed. CSV/BI4/H5/DAT/VTK/PNG payloads
were not opened or hashed; no scientific job or shared-state mutation occurred.
This package grants no case credit or Q-N/Q-E status.
