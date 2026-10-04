# F6 successor 061 — unit-bearing FloatingInfo alias fix

This source-only successor preserves the immutable 059 worker and fixes one
decoder defect. The genuine semicolon FloatingInfo header normalizes

- `fomega.x [rad/s]` to `fomegaxrads`,
- `fvel.x [m/s]` to `fvelxms`, and
- `center.x [m]` to `centerxm`,

with the corresponding y/z fields. The 059 aliases matched punctuation-free
fields without the unit suffix, so the genuine 052 output reported both
selected rows as unresolved even though the header and numeric rows were
present. The successor adds the unit-bearing aliases while retaining the
explicit semicolon parser, bounded prefix, frame-zero/first-positive row
selection, and all H5/XML semantics from 059.

The synthetic regression fixture uses the actual header spellings and a zero
row plus the genuine first-positive time shape. It confirms that 059 remains
unresolved for those normalized names and that successor061 returns complete
omega, linear velocity, and center vectors for both selected rows.

The genuine 052 output remains a read-only observation. It reports a direct
native Type2 fit of omega `[0, 0, 0]` at frame zero and a nonzero first-saved
fit near `[0.0298555922, 0.0378212146, 0.0599352867]` rad/s at about
`0.050061826 s`, with residual RMS near `1.03e-8 m/s`; the prior actual CSV
decode is retained as unresolved until Root runs the successor. The exact XML
still declares angularvelini `[0.08, 0.12, 0.06]` rad/s. Physical mass `128 kg`
and native support mass `256 kg` remain separate, with no rescaling and no
physics-zero-start conclusion.

The request is disabled (`launch=false`, `launch_allowed=false`). This scope
reads no H5, CSV, BI4, arrays, jobs, solver output, or rendering output. It
adds no case count, precision claim, q_n claim, root-cause claim, or visual
acceptance.
